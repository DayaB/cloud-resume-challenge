import unittest
import boto3
import random
from moto import mock_dynamodb2
from . import index

class TestDynamo(unittest.TestCase):
    def setUp(self):
        pass

    @mock_dynamodb2
    def test_get_visitors_counter(self):
        # Set up a mock dynamodb using ddbmock
        tablename = 'unittest'
        randominterger = random.randint(1, 100)
        # Create mock dynamodb connection
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        # Create table
        index.create_dynamo_table(tablename, dynamodb)
        print('Table "{}" successfully created.'.format(tablename))
        # Put default value into the table
        index.put_table_counters(tablename, randominterger, dynamodb)
        print('Inserted value of {} into the table'.format(randominterger))
        # Get the value of the table
        result = index.get_visitors_counter(tablename, dynamodb)
        print('Retreived value of {} from table'.format(result))
        # Assert the result of the put matches the random integer
        self.assertEqual(randominterger, result)
        # Update the table
        index.update_table_counters(tablename, randominterger + 1, dynamodb)
        # Get the new value
        result = index.get_visitors_counter(tablename, dynamodb)
        print('Retreived updated value of {}'.format(result))
        self.assertEqual(randominterger + 1, result)



