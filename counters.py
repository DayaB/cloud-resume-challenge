#!/usr/bin/env python3
import boto3
import json
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from decimal import Decimal

# Get the service resource.
dynamodb = boto3.resource('dynamodb')

# Variables
tablename = 'counters'


def create_dynamo_table(tablename):
    # Create the DynamoDB table
    try:
        table = dynamodb.create_table(
            TableName=tablename,
            KeySchema=[
                {
                    'AttributeName': 'website',
                    'KeyType': 'HASH'
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': 'website',
                    'AttributeType': 'S'
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        table.meta.client.get_waiter('table_exists').wait(TableName=tablename)

    except:
        pass


def get_visitors_counter(tablename):
    table = dynamodb.Table(tablename)
    # Read it and print the output
    try:
        response = table.query(
            KeyConditionExpression=Key('website').eq('resume.trentnielsen.me'))
    except ClientError as e:
        message = e.response['Error']['Message']
        return message
    else:
        try:
            visitors = response['Items'][0]['visitors']
            return visitors
        except KeyError:
            return 'Item response empty'


def put_table_counters(tablename, value):
    table = dynamodb.Table(tablename)
    try:
        get_visitors_counter(tablename)
    except IndexError:
        try:
            response = table.put_item(
                Item={
                    'website': 'resume.trentnielsen.me',
                    'visitors': value
                }
            )

        except ClientError as e:
            return e.response['Error']['Message']
        else:
            return json.dumps(response, indent=4, sort_keys=True)


def update_table_counters(tablename, value):
    table = dynamodb.Table(tablename)
    # Update it
    try:
        response = table.update_item(
            Key={
                'website': 'resume.trentnielsen.me'
            },
            UpdateExpression='set visitors=:v',
            ExpressionAttributeValues={
                ':v': Decimal(value),
            },
            ReturnValues="UPDATED_NEW"
        )
        return response
    except ClientError as e:
        return e.response['Error']['Message']

def delete_table(tablename):
    try:
        table = dynamodb.Table(tablename)
        response = table.delete(tablename)
    except:
        return 'error'


create_dynamo_table('counters')
# Set the value of 0 of the key counters
put_table_counters('counters', 0)
visitors = get_visitors_counter('counters')
print('Printing visitors count: {}'.format(visitors))
try:
    update_table_counters('counters', visitors + 1)
except TypeError:
    print('ERROR: No value returned, update failed')
