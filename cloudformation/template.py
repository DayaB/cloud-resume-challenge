#!/usr/bin/env python3
import os
import json
from pathlib import Path

import troposphere.s3 as s3
from troposphere import Template, GetAtt, Join, Ref, Output, Select, Split
from troposphere.apigateway import RestApi, Method
from troposphere.apigateway import Resource, MethodResponse
from troposphere.apigateway import Integration, IntegrationResponse
from troposphere.apigateway import Deployment, Stage
from troposphere.iam import Role, Policy
from troposphere.awslambda import Function, Code
from troposphere.dynamodb import (KeySchema, AttributeDefinition, ProvisionedThroughput)
from troposphere.dynamodb import Table
from troposphere.s3 import *
import troposphere.cloudfront as cf
from troposphere.certificatemanager import Certificate, DomainValidationOption
from troposphere.route53 import RecordSetType, AliasTarget

# Function that saves the file , but makes sure it exists first.
def save_to_file(template, settings_file_path='./cloudformation/template.json'):
    # Create settings file if it doesn't exist:
    settings_file = Path(settings_file_path)
    if settings_file.is_file():
        with open(settings_file_path, 'w+') as outfile:
            json.dump(template, outfile, indent=2)
    else:
        with open(settings_file_path, 'a'):
            os.utime(settings_file_path, None)
        with open(settings_file_path, 'w+') as outfile:
            json.dump(template, outfile, indent=2)


app_group = "Trent-Lab-Cloud-Resume-Challenge"
app_group_l = app_group.lower()
app_group_ansi = app_group_l.replace("-", "")
cfront_zone_id = 'Z2FDTNDATAQYW2'
env = 'Staging-A'
env_l = env.lower()

# Create Default Tags
DefaultTags = Tags(Business='YIT') + \
              Tags(Lab='True')

# Set template variables
stage_name = 'v1'

##### Dynamo Variables
readunits = 5
writeunits = 5
# The name of the table
hashkeyname = 'counters'
# Table data type (N is for number/integer)
hashkeytype = 'N'

dns_domain = 'trentnielsen.me'

# Prepare Template
t = Template()
t.set_description('YIT: {}'.format(app_group))

################################################################################################################
# CloudFront and S3 for static hosting
################################################################################################################

redirect_domains = {
    'resume.trentnielsen.me': {
        'zone_name': 'trentnielsen.me',
        'redirect_target': 'resume.trentnielsen.me',
        'alt_sub': 'www',
    },
}

for src_domain, domain_info in redirect_domains.items():

    bucketResourceName = "{}0{}0Bucket".format(app_group_ansi, src_domain.replace('.', '0'))

    redirectBucket = t.add_resource(Bucket(
        bucketResourceName,
        BucketName='{}'.format(src_domain),
        Tags=DefaultTags + Tags(Component='{}'.format(src_domain)),
        WebsiteConfiguration=(s3.WebsiteConfiguration(
            IndexDocument='index.html'
        ))
    ))

    # Set some cdn based values and defaults
    dns_domain = domain_info['zone_name']
    cdn_domain = '{}'.format(src_domain)
    max_ttl = 31536000,
    default_ttl = 86400,

    # If an alt_sub domain is not specified use empty string
    if domain_info['alt_sub'] != '':
        alternate_name = '{}.{}'.format(domain_info['alt_sub'], src_domain)
    else:
        alternate_name = ''

    # Provision certificate for CDN
    cdnCertificate = t.add_resource(Certificate(
        'cdnCertificate{}'.format(src_domain.replace('.', '0')),
        DomainName=cdn_domain,
        DependsOn=redirectBucket,
        SubjectAlternativeNames=[alternate_name],
        DomainValidationOptions=[DomainValidationOption(
            DomainName=cdn_domain,
            ValidationDomain=dns_domain
        )],
        ValidationMethod='DNS',
        Tags=DefaultTags + Tags(Name='{}-{}'.format(env_l, app_group_l))
    ))

    # Provision the CDN Origin
    cdnOrigin = cf.Origin(
        Id='{}-{}-{}'.format(env_l, app_group_l, src_domain),
        DomainName=Select(1, Split('//', GetAtt(redirectBucket, 'WebsiteURL'))),
        CustomOriginConfig=cf.CustomOriginConfig(
            HTTPPort=80,
            HTTPSPort=443,
            OriginProtocolPolicy='http-only',
            OriginSSLProtocols=['TLSv1.2'],
        )
    )

    # Provision the CDN Distribution
    cdnDistribution = t.add_resource(cf.Distribution(
        'cdnDistribution{}'.format(src_domain.replace('.', '0')),
        DependsOn='cdnCertificate{}'.format(src_domain.replace('.', '0')),
        DistributionConfig=cf.DistributionConfig(
            Comment='{} - {}'.format(env, cdn_domain),
            Enabled=True,
            PriceClass='PriceClass_All',
            HttpVersion='http2',
            Origins=[
                cdnOrigin,
            ],
            Aliases=[cdn_domain, alternate_name],
            ViewerCertificate=cf.ViewerCertificate(
                AcmCertificateArn=Ref(cdnCertificate),
                SslSupportMethod='sni-only',
                MinimumProtocolVersion='TLSv1.2_2018',
            ),
            DefaultCacheBehavior=cf.DefaultCacheBehavior(
                AllowedMethods=['GET', 'HEAD', 'OPTIONS'],
                CachedMethods=['GET', 'HEAD'],
                ViewerProtocolPolicy='redirect-to-https',
                TargetOriginId='{}-{}-{}'.format(env_l, app_group_l, src_domain),
                ForwardedValues=cf.ForwardedValues(
                    Headers=[
                        "Accept-Encoding"
                    ],
                    QueryString=True,
                ),
                MinTTL=0,
                MaxTTL=int(max_ttl[0]),
                DefaultTTL=int(default_ttl[0]),
                SmoothStreaming=False,
                Compress=True
            ),
            CustomErrorResponses=[
                cf.CustomErrorResponse(
                    ErrorCachingMinTTL='0',
                    ErrorCode='403',
                ),
                cf.CustomErrorResponse(
                    ErrorCachingMinTTL='0',
                    ErrorCode='404',
                ),
                cf.CustomErrorResponse(
                    ErrorCachingMinTTL='0',
                    ErrorCode='500',
                ),
                cf.CustomErrorResponse(
                    ErrorCachingMinTTL='0',
                    ErrorCode='501',
                ),
                cf.CustomErrorResponse(
                    ErrorCachingMinTTL='0',
                    ErrorCode='502',
                ),
                cf.CustomErrorResponse(
                    ErrorCachingMinTTL='0',
                    ErrorCode='503',
                ),
                cf.CustomErrorResponse(
                    ErrorCachingMinTTL='0',
                    ErrorCode='504',
                ),
            ],
        ),
        Tags=DefaultTags
    ))

    cdnARecord = t.add_resource(RecordSetType(
        "{}{}Adns".format(app_group_ansi, src_domain.replace('.', '0')),
        HostedZoneName='{}.'.format(dns_domain),
        Comment="{} domain record".format(cdn_domain),
        Name='{}'.format(cdn_domain),
        Type="A",
        AliasTarget=AliasTarget(
            HostedZoneId=cfront_zone_id,
            DNSName=GetAtt(cdnDistribution, "DomainName")
        )
    ))

    cdnAAAARecord = t.add_resource(RecordSetType(
        "{}{}AAAAdns".format(app_group_ansi, src_domain.replace('.', '0')),
        HostedZoneName='{}.'.format(dns_domain),
        Comment="{} domain record".format(cdn_domain),
        Name='{}'.format(cdn_domain),
        Type="AAAA",
        AliasTarget=AliasTarget(
            HostedZoneId=cfront_zone_id,
            DNSName=GetAtt(cdnDistribution, "DomainName")
        )
    ))

    if domain_info['alt_sub'] != '':
        cdnAlternativeARecord = t.add_resource(RecordSetType(
            "{}{}AlternativeAdns".format(app_group_ansi, src_domain.replace('.', '0')),
            HostedZoneName='{}.'.format(dns_domain),
            Comment="{} domain record".format(alternate_name),
            Name='{}'.format(alternate_name),
            Type="A",
            AliasTarget=AliasTarget(
                HostedZoneId=cfront_zone_id,
                DNSName=GetAtt(cdnDistribution, "DomainName")
            )
        ))

        cdnAlternativeAAAARecord = t.add_resource(RecordSetType(
            "{}{}AlternativeAAAAdns".format(app_group_ansi, src_domain.replace('.', '0')),
            HostedZoneName='{}.'.format(dns_domain),
            Comment="{} domain record".format(alternate_name),
            Name='{}'.format(alternate_name),
            Type="AAAA",
            AliasTarget=AliasTarget(
                HostedZoneId=cfront_zone_id,
                DNSName=GetAtt(cdnDistribution, "DomainName")
            )
        ))

        # Redirect outputs
        t.add_output([
            Output(
                'CDNDomainOutput{}'.format(src_domain.replace('.', '0')),
                Description="Domain for CDN",
                Value=GetAtt(cdnDistribution, 'DomainName'),
            )
        ])

#####################################################################################################################
# API Gateway
#####################################################################################################################
rest_api = t.add_resource(RestApi(
    "api",
    Name="{}-{}".format(env_l, app_group_l)
))

#####################################################################################################################
# DynamoDB table
#####################################################################################################################
myDynamoDB = t.add_resource(Table(
    "myDynamoDBTable",
    TableName='counters',
    AttributeDefinitions=[
        AttributeDefinition(
            AttributeName='website',
            AttributeType='S'
        )
    ],
    KeySchema=[
        KeySchema(
            AttributeName='website',
            KeyType='HASH'
        )
    ],
    ProvisionedThroughput=ProvisionedThroughput(
        ReadCapacityUnits=readunits,
        WriteCapacityUnits=writeunits
    )
))

#####################################################################################################################
# Lambda
#####################################################################################################################
# Create a Lambda function that will be mapped
code = [
    "var response = require('cfn-response');",
    "exports.handler = function(event, context) {",
    "   context.succeed('foobar!');",
    "   return 'foobar!';",
    "};",
]

# Create a role for the lambda function
t.add_resource(Role(
    "LambdaExecutionRole",
    Path="/",
    Policies=[Policy(
        PolicyName="root",
        PolicyDocument={
            "Version": "2012-10-17",
            "Statement": [{
                "Action": ["logs:*"],
                "Resource": "arn:aws:logs:*:*:*",
                "Effect": "Allow"
            },
                {
                "Action": ["lambda:*"],
                "Resource": "*",
                "Effect": "Allow"
                },
                {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:BatchGetItem",
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:BatchWriteItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem"
                ],
                "Resource": GetAtt('myDynamoDBTable', 'Arn')
                }]
        })],
    AssumeRolePolicyDocument={"Version": "2012-10-17", "Statement": [
        {
            "Action": ["sts:AssumeRole"],
            "Effect": "Allow",
            "Principal": {
                "Service": [
                    "lambda.amazonaws.com",
                    "apigateway.amazonaws.com"
                ]
            }
        }
    ]},
))

function = t.add_resource(Function(
    "function",
    Code=Code(
        ZipFile=Join("", code)
    ),
    Handler="index.handler",
    Role=GetAtt("LambdaExecutionRole", "Arn"),
    Runtime="python3.7",
))

# Create a resource to map the lambda function to
resource = t.add_resource(Resource(
    "resource",
    RestApiId=Ref(rest_api),
    PathPart="dynamo",
    ParentId=GetAtt("api", "RootResourceId"),
))

# Create a get method for the API gateway
getmethod = t.add_resource(Method(
    "getmethod",
    DependsOn='function',
    RestApiId=Ref(rest_api),
    AuthorizationType="NONE",
    ResourceId=Ref(resource),
    HttpMethod="GET",
    Integration=Integration(
        Credentials=GetAtt("LambdaExecutionRole", "Arn"),
        Type="AWS",
        IntegrationHttpMethod='POST',
        IntegrationResponses=[
            IntegrationResponse(
                StatusCode='200'
            )
        ],
        Uri=Join("", [
            "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/",
            GetAtt("function", "Arn"),
            "/invocations"
        ])
    ),
    MethodResponses=[
        MethodResponse(
            "CatResponse",
            StatusCode='200'
        )
    ]
))

# Create an OPTIONS method for the API gateway for CORS
optionsmethod = t.add_resource(Method(
    "optionsmethod",
    DependsOn='getmethod',
    RestApiId=Ref(rest_api),
    AuthorizationType="NONE",
    ResourceId=Ref(resource),
    HttpMethod="OPTIONS",
    MethodResponses=[
        MethodResponse(
            "CatResponse",
            StatusCode='200',
            ResponseModels={
                'application/json': 'Empty'
            }
        )
    ],
    Integration=Integration(
        Credentials=GetAtt("LambdaExecutionRole", "Arn"),
        PassthroughBehavior='WHEN_NO_MATCH',
        Type="MOCK",
        IntegrationHttpMethod='POST',
        IntegrationResponses=[
            IntegrationResponse(
                StatusCode='200',
                ResponseTemplates={
                    'application/json': ''
                },
                ResponseParameters={
                    'method.response.header.Access-Control-Allow-Headers': "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
                    'method.response.header.Access-Control-Allow-Methods': "'GET,OPTIONS'",
                    'method.response.header.Access-Control-Allow-Origin': "'*'"
                },
            )
        ],
        Uri=Join("", [
            "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/",
            GetAtt("function", "Arn"),
            "/invocations"
        ]),

        RequestTemplates={
            'application/json': '{"statusCode": 200}'
        },
    ),
))

deployment = t.add_resource(Deployment(
    "%sDeployment" % stage_name,
    DependsOn="optionsmethod",
    RestApiId=Ref(rest_api),
))

stage = t.add_resource(Stage(
    '%sStage' % stage_name,
    StageName=stage_name,
    RestApiId=Ref(rest_api),
    DeploymentId=Ref(deployment)
))

# Create cname record for all mount points
apiCname = t.add_resource(RecordSetType(
    'apiCname',
    HostedZoneName='{}.'.format(dns_domain),
    Comment="{} API gateway domain record".format(app_group_l),
    Name='{}.{}'.format('api', dns_domain),
    Type="CNAME",
    TTL="900",
    ResourceRecords=[Join("", [
            Ref(rest_api),
            ".execute-api.us-east-1.amazonaws.com"
        ])]
))

#####################################################################################################################
# Output
#####################################################################################################################

# API gateway outputs
t.add_output([
    Output(
        "ApiEndpoint",
        Value=Join("", [
            "https://",
            Ref(rest_api),
            ".execute-api.us-east-1.amazonaws.com/",
            stage_name
        ]),
        Description="Endpoint for this stage of the api"
    ),
])

# DynamoDB outputs
t.add_output(Output(
    "TableName",
    Value=Ref(myDynamoDB),
    Description="Table name of the newly create DynamoDB table",
))

# Load the data into a json object
json_data = json.loads(t.to_json())

# Save the file to disk
save_to_file(json_data)
