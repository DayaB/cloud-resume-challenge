#!/usr/bin/env python3
import os
import json
from pathlib import Path

import troposphere.s3 as s3
from troposphere import Template, GetAtt, Join, Ref, Output
from troposphere import Tags
from troposphere.apigateway import RestApi, Method
from troposphere.apigateway import Resource, MethodResponse
from troposphere.apigateway import Integration, IntegrationResponse
from troposphere.apigateway import Deployment, Stage
from troposphere.apigateway import ApiKey, StageKey
from troposphere.iam import Role, Policy
from troposphere.awslambda import Function, Code
from troposphere.dynamodb import (KeySchema, AttributeDefinition, ProvisionedThroughput)
from troposphere.dynamodb import Table
from troposphere.cloudfront import Distribution, DistributionConfig
from troposphere.cloudfront import Origin, DefaultCacheBehavior
from troposphere.cloudfront import ForwardedValues
from troposphere.cloudfront import S3OriginConfig

# Function that saves the file , but makes sure it exists first.
def save_to_file(template, settings_file_path='./template.json'):
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

# Create Default Tags
DefaultTags = Tags(Business='YIT') + \
              Tags(Lab='True')

# Set template variables
stage_name = 'v1'

##### Dynamo Variables
readunits = 1
writeunits = 1
# The name of the table
hashkeyname = 'counters'
# Table data type (N is for number/integer)
hashkeytype = 'N'

# Prepare Template
t = Template()
t.set_description('YIT: Trent - Lab Infrastructure')

#####################################################################################################################
# S3 Bucket for Backups
#####################################################################################################################
bucket = t.add_resource(s3.Bucket(
    'bucket',
    BucketName='trentnielsen.me',
    Tags=DefaultTags,
    PublicAccessBlockConfiguration=s3.PublicAccessBlockConfiguration(
        BlockPublicAcls=True,
        BlockPublicPolicy=True,
        IgnorePublicAcls=True,
        RestrictPublicBuckets=True,
    ),
    WebsiteConfiguration=(s3.WebsiteConfiguration(
        IndexDocument='index.html'
    ))
))

#####################################################################################################################
# DNS record for the resume file
#####################################################################################################################
dnsRecord = t.add_resource(RecordSetType(
                    'dnsrecord',
                    HostedZoneName='trentnielsen.me',
                    Comment='CF generated hostname for cloud resume challenge',
                    Name='resume.trentnielsen.me',
                    Type="A",
                    TTL="600",
                    ResourceRecords=[GetAtt(bucket, 'DomainName')],
                ))

#####################################################################################################################
# CloudFront
#####################################################################################################################
distribution = t.add_resource(Distribution(
    "distribution",
    DistributionConfig=DistributionConfig(
        Origins=[Origin(Id="Origin 1", DomainName=Ref(dnsRecord),
                        S3OriginConfig=S3OriginConfig())],
        DefaultCacheBehavior=DefaultCacheBehavior(
            TargetOriginId="Origin 1",
            ForwardedValues=ForwardedValues(
                QueryString=False
            ),
            ViewerProtocolPolicy="allow-all"),
        Enabled=True,
        HttpVersion='http2'
    )
))



#####################################################################################################################
# API Gateway
#####################################################################################################################
rest_api = t.add_resource(RestApi(
    "api",
    Name="production-a-cloudresumechallenge"
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
            }, {
                "Action": ["lambda:*"],
                "Resource": "*",
                "Effect": "Allow"
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

# Create a Lambda API method for the Lambda resource
method = t.add_resource(Method(
    "LambdaMethod",
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
            "arn:aws:apigateway:us-west-2:lambda:path/2015-03-31/functions/",
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

deployment = t.add_resource(Deployment(
    "%sDeployment" % stage_name,
    DependsOn="LambdaMethod",
    RestApiId=Ref(rest_api),
))

stage = t.add_resource(Stage(
    '%sStage' % stage_name,
    StageName=stage_name,
    RestApiId=Ref(rest_api),
    DeploymentId=Ref(deployment)
))

key = t.add_resource(ApiKey(
    "ApiKey",
    StageKeys=[StageKey(
        RestApiId=Ref(rest_api),
        StageName=Ref(stage)
    )]
))

#####################################################################################################################
# DynamoDB table
#####################################################################################################################
myDynamoDB = t.add_resource(Table(
    "myDynamoDBTable",
    AttributeDefinitions=[
        AttributeDefinition(
            AttributeName=hashkeyname,
            AttributeType=hashkeytype
        ),
    ],
    KeySchema=[
        KeySchema(
            AttributeName=hashkeyname,
            KeyType="HASH"
        )
    ],
    ProvisionedThroughput=ProvisionedThroughput(
        ReadCapacityUnits=readunits,
        WriteCapacityUnits=writeunits
    )
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
            ".execute-api.us-west-2.amazonaws.com/",
            stage_name
        ]),
        Description="Endpoint for this stage of the api"
    ),
    Output(
        "ApiKey",
        Value=Ref(key),
        Description="API key"
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
