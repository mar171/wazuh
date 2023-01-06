import pytest
import os
import sys
import boto3
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, mock_open

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '.'))
import aws_utils as utils

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'buckets_s3'))
import aws_bucket
import vpcflow

VPC_SCHEMA_COUNT = 8

TEST_VPCFLOW_SCHEMA = "schema_vpcflow_test.sql"
TEST_EMPTY_TABLE_SCHEMA = "schema_empty_vpc_table.sql"

TEST_FLOW_LOG_ID = 'fl-1234'
TEST_TABLE_NAME = 'vpcflow'
TEST_LOG_KEY = 'vpc/AWSLogs/123456789/vpcflowlogs/us-east-1/2019/04/15/123456789_vpcflowlogs_us-east-1_fl-1234_20190415T0945Z_c23ab7.log.gz'

SQL_GET_DATE_LAST_LOG_PROCESSED = """SELECT created_date FROM {table_name} ORDER BY log_key DESC LIMIT 1;"""
SQL_COUNT_ROWS = """SELECT count(*) FROM {table_name};"""
SQL_GET_ROW = "SELECT bucket_path, aws_account_id, aws_region, flow_log_id, log_key, created_date FROM {table_name};"


@patch('aws_bucket.AWSLogsBucket.__init__')
def test_AWSVPCFlowBucket__init__(mock_logs_bucket):
    """Test if the instances of CiscoUmbrella are created properly."""
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket)
    assert instance.service == 'vpcflowlogs'

    mock_logs_bucket.assert_called_once()


@patch('aws_bucket.AWSLogsBucket.__init__')
def test_AWSVPCFlowBucket_load_information_from_file(mock_logs_bucket):
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket)

    data = '2 123456789123 eni-12345678912345678 0.0.0.0 0.0.0.0 3500 52000 6 39 4698 1622505433 1622505730 ACCEPT OK'

    expected_result = [{
        'version': '2', 'account_id': '123456789123',
        'interface_id': 'eni-12345678912345678',
        'srcaddr': '0.0.0.0', 'dstaddr': '0.0.0.0',
        'srcport': '3500', 'dstport': '52000',
        'protocol': '6', 'packets': '39',
        'bytes': '4698', 'start': '1622505433',
        'end': '1622505730', 'action': 'ACCEPT', 'log_status': 'OK'
    }]
    expected_result[0].update({'source': 'vpc'})
    expected_result[0]["start"] = datetime.utcfromtimestamp(int(expected_result[0]["start"])).strftime(
        '%Y-%m-%dT%H:%M:%SZ')
    expected_result[0]["end"] = datetime.utcfromtimestamp(int(expected_result[0]["end"])).strftime('%Y-%m-%dT%H:%M:%SZ')

    with patch('aws_bucket.AWSBucket.decompress_file', mock_open(read_data=data)):
        assert instance.load_information_from_file(utils.TEST_LOG_KEY) == list(expected_result)


@pytest.mark.parametrize('access_key', [None, utils.TEST_ACCESS_KEY])
@pytest.mark.parametrize('secret_key', [None, utils.TEST_SECRET_KEY])
@pytest.mark.parametrize('profile', [None, utils.TEST_AWS_PROFILE])
@patch('aws_bucket.AWSLogsBucket.__init__')
def test_AWSVPCFlowBucket_get_ec2_client(mock_logs_bucket, access_key, secret_key, profile):
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket)
    region = utils.TEST_REGION

    conn_args = {'region_name': region}

    if access_key is not None and secret_key is not None:
        conn_args['aws_access_key_id'] = access_key
        conn_args['aws_secret_access_key'] = secret_key
    elif profile is not None:
        conn_args['profile_name'] = profile

    with patch('boto3.Session') as mock_session:
        instance.connection_config = MagicMock()
        instance.get_ec2_client(access_key, secret_key, region, profile)
        mock_session.assert_called_once_with(**conn_args)


@patch('aws_bucket.AWSLogsBucket.__init__')
def test_AWSVPCFlowBucket_get_ec2_client_ko(mock_logs_bucket):
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket)

    with patch('boto3.Session'), \
            pytest.raises(SystemExit) as e:
        instance.get_ec2_client(utils.TEST_ACCESS_KEY, utils.TEST_SECRET_KEY, utils.TEST_REGION, utils.TEST_AWS_PROFILE)
    assert e.value.code == utils.INVALID_CREDENTIALS_ERROR_CODE


@patch('vpcflow.AWSVPCFlowBucket.get_ec2_client')
@patch('aws_bucket.AWSLogsBucket.__init__')
def test_AWSVPCFlowBucket_get_flow_logs_ids(mock_logs_bucket, mock_get_ec2_client):
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket)

    ec2_client = mock_get_ec2_client.return_value
    ec2_client.describe_flow_logs.return_value = {
        'FlowLogs': [
            {
                'FlowLogId': 'Id1',
                'OtherFields': 'fields'
            },
            {
                'FlowLogId': 'Id2',
                'OtherFields': 'fields'
            },
            {
                'FlowLogId': 'Id3',
                'OtherFields': 'fields'
            },
        ],
        'NextToken': 'string'
    }

    assert ['Id1', 'Id2', 'Id3'] == instance.get_flow_logs_ids(utils.TEST_ACCESS_KEY, utils.TEST_SECRET_KEY,
                                                               utils.TEST_REGION, utils.TEST_AWS_PROFILE)


@pytest.mark.parametrize('log_file, bucket, account_id, region, expected_result', [
    (TEST_LOG_KEY, utils.TEST_BUCKET, utils.TEST_ACCOUNT_ID, utils.TEST_REGION, True),
    ("", utils.TEST_BUCKET, utils.TEST_ACCOUNT_ID, utils.TEST_REGION, False),
    (TEST_LOG_KEY, utils.TEST_BUCKET, "", utils.TEST_REGION, False),
])
@patch('aws_bucket.AWSLogsBucket.__init__', side_effect=aws_bucket.AWSLogsBucket.__init__)
def test_AWSVPCFlowBucket_already_processed(mock_logs_bucket, custom_database, log_file, bucket, account_id, region,
                                            expected_result):
    utils.database_execute_script(custom_database, TEST_VPCFLOW_SCHEMA)

    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket, bucket=utils.TEST_BUCKET)
    instance.db_connector = custom_database
    instance.db_cursor = instance.db_connector.cursor()
    instance.db_table_name = TEST_TABLE_NAME
    instance.aws_account_id = utils.TEST_ACCOUNT_ID

    assert instance.already_processed(downloaded_file=log_file, aws_account_id=account_id,
                                      aws_region=region, flow_log_id=TEST_FLOW_LOG_ID) == expected_result


@patch('aws_bucket.AWSLogsBucket.__init__')
def test_AWSVPCFlowBucket_get_days_since_today(mock_logs_bucket):
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket)
    test_date = "20220630"

    date = datetime.strptime(test_date, "%Y%m%d")
    delta = datetime.utcnow() - date + timedelta(days=1)

    assert instance.get_days_since_today(test_date) == delta.days


@patch('vpcflow.AWSVPCFlowBucket.get_date_last_log')
@patch('vpcflow.AWSVPCFlowBucket.get_days_since_today', return_value=10)
@patch('aws_bucket.AWSLogsBucket.__init__')
def test_AWSVPCFlowBucket_get_date_list(mock_logs_bucket, mock_days_since_today, mock_date_last_log):
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket)
    instance.date_format = "%Y/%m/%d"

    num_days = instance.get_days_since_today(mock_date_last_log(utils.TEST_ACCOUNT_ID, utils.TEST_REGION))

    date_list_time = [datetime.utcnow() - timedelta(days=x) for x in range(0, num_days)]

    assert instance.get_date_list(utils.TEST_ACCOUNT_ID, utils.TEST_REGION, TEST_FLOW_LOG_ID) == [
        datetime.strftime(date, instance.date_format)
        for date in reversed(date_list_time)]


@pytest.mark.parametrize('only_logs_after', [utils.TEST_ONLY_LOGS_AFTER, None])
@pytest.mark.parametrize('reparse', [True, False])
@patch('aws_bucket.AWSLogsBucket.__init__', side_effect=aws_bucket.AWSLogsBucket.__init__)
def test_AWSVPCFlowBucket_get_date_last_log(mock_logs_bucket, custom_database, reparse, only_logs_after):
    utils.database_execute_script(custom_database, TEST_VPCFLOW_SCHEMA)

    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket, bucket=utils.TEST_BUCKET, reparse=reparse,
                                       only_logs_after=only_logs_after)

    instance.db_connector = custom_database
    instance.db_cursor = instance.db_connector.cursor()
    instance.db_table_name = TEST_TABLE_NAME

    last_date_processed = instance.only_logs_after.strftime('%Y%m%d') if \
        instance.only_logs_after and instance.reparse else None

    if not last_date_processed:
        query_date_last_log = utils.database_execute_query(instance.db_connector,
                                                           SQL_GET_DATE_LAST_LOG_PROCESSED.format(
                                                               table_name=instance.db_table_name))
        db_date = str(query_date_last_log)

        if instance.only_logs_after:
            last_date_processed = db_date if datetime.strptime(db_date, '%Y%m%d') > instance.only_logs_after else \
                datetime.strftime(instance.only_logs_after, '%Y%m%d')
        else:
            last_date_processed = db_date

    assert instance.get_date_last_log(utils.TEST_ACCOUNT_ID, utils.TEST_REGION, TEST_FLOW_LOG_ID) == last_date_processed


@patch('aws_bucket.AWSLogsBucket.__init__', side_effect=aws_bucket.AWSLogsBucket.__init__)
def test_AWSVPCFlowBucket_get_date_last_log_db_error(mock_logs_bucket, custom_database):
    utils.database_execute_script(custom_database, TEST_VPCFLOW_SCHEMA)

    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket, bucket='db_exception_bucket',
                                       only_logs_after=utils.TEST_ONLY_LOGS_AFTER)

    instance.db_connector = custom_database
    instance.db_cursor = instance.db_connector.cursor()
    instance.db_table_name = TEST_TABLE_NAME

    last_date_processed = instance.only_logs_after.strftime('%Y%m%d') if instance.only_logs_after \
        else instance.default_date.strftime('%Y%m%d')

    assert instance.get_date_last_log(utils.TEST_ACCOUNT_ID, utils.TEST_REGION, TEST_FLOW_LOG_ID) == last_date_processed


@pytest.mark.parametrize('account_id', [[utils.TEST_ACCOUNT_ID], None])
@pytest.mark.parametrize('regions', [[utils.TEST_REGION], None])
@patch('vpcflow.AWSVPCFlowBucket.iter_files_in_bucket')
@patch('vpcflow.AWSVPCFlowBucket.get_flow_logs_ids', return_value=['Id1'])
@patch('vpcflow.AWSVPCFlowBucket.get_date_list', return_value=['2023/01/05'])
@patch('vpcflow.AWSVPCFlowBucket.db_maintenance')
@patch('aws_bucket.AWSBucket.find_account_ids', return_value=[utils.TEST_ACCOUNT_ID])
@patch('aws_bucket.AWSBucket.find_regions', side_effect=[[utils.TEST_REGION], None])
@patch('aws_bucket.AWSLogsBucket.__init__')
def test_AWSVPCFlowBucket_iter_regions_and_accounts(mock_logs_bucket, mock_find_regions, mock_accounts,
                                                    mock_maintenance, mock_get_date_list, mock_get_flow_logs_ids,
                                                    mock_iter_files_in_bucket,
                                                    regions, account_id):
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket)

    instance.access_key = utils.TEST_ACCESS_KEY
    instance.secret_key = utils.TEST_SECRET_KEY
    instance.profile_name = utils.TEST_AWS_PROFILE

    instance.iter_regions_and_accounts(account_id, regions)

    if not account_id:
        mock_accounts.assert_called_once()
        account_id = instance.find_account_ids()
    for aws_account_id in account_id:
        if not regions:
            mock_find_regions.assert_called_with(aws_account_id)
            regions = instance.find_regions(aws_account_id)
            if not regions:
                continue
        for aws_region in regions:
            mock_get_flow_logs_ids.assert_called_with(instance.access_key, instance.secret_key, aws_region,
                                                      profile_name=instance.profile_name)
            flow_logs_ids = instance.get_flow_logs_ids(instance.access_key, instance.secret_key, aws_region,
                                                       profile_name=instance.profile_name)
            for flow_log_id in flow_logs_ids:
                mock_get_date_list.assert_called_with(aws_account_id, aws_region, flow_log_id)
                date_list = instance.get_date_list(aws_account_id, aws_region, flow_log_id)
                for date in date_list:
                    mock_iter_files_in_bucket.assert_called_with(aws_account_id, aws_region, date, flow_log_id)
                mock_maintenance.assert_called_with(aws_account_id, aws_region, flow_log_id)


@pytest.mark.parametrize('flow_log_id', [TEST_FLOW_LOG_ID, "other-id"])
@pytest.mark.parametrize('region', [utils.TEST_REGION, "invalid_region"])
@patch('aws_bucket.AWSLogsBucket.__init__', side_effect=aws_bucket.AWSLogsBucket.__init__)
def test_AWSVPCFlowBucket_db_count_region(mock_logs_bucket, custom_database, region, flow_log_id):
    utils.database_execute_script(custom_database, TEST_VPCFLOW_SCHEMA)
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket, bucket=utils.TEST_BUCKET)
    instance.db_connector = custom_database
    instance.db_cursor = instance.db_connector.cursor()
    instance.db_table_name = TEST_TABLE_NAME

    expected_count = VPC_SCHEMA_COUNT if region == utils.TEST_REGION and flow_log_id == TEST_FLOW_LOG_ID else 0
    assert instance.db_count_region(utils.TEST_ACCOUNT_ID, region, flow_log_id) == expected_count


@pytest.mark.parametrize('expected_db_count', [VPC_SCHEMA_COUNT, 0])
@patch('aws_bucket.AWSLogsBucket.__init__', side_effect=aws_bucket.AWSLogsBucket.__init__)
def test_AWSVPCFlowBucket_db_maintenance(mock_logs_bucket, custom_database, expected_db_count):
    """Test 'db_maintenance' function deletes rows from a table until the count is equal to 'retain_db_records'."""
    utils.database_execute_script(custom_database, TEST_VPCFLOW_SCHEMA)
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket, bucket=utils.TEST_BUCKET)
    instance.db_connector = custom_database
    instance.db_cursor = instance.db_connector.cursor()
    instance.db_table_name = TEST_TABLE_NAME
    instance.retain_db_records = expected_db_count

    assert utils.database_execute_query(instance.db_connector, SQL_COUNT_ROWS.format(
        table_name=instance.db_table_name)) == VPC_SCHEMA_COUNT

    with patch('aws_bucket.AWSBucket.db_count_region', return_value=VPC_SCHEMA_COUNT):
        instance.db_maintenance(aws_account_id=utils.TEST_ACCOUNT_ID, aws_region=utils.TEST_REGION,
                                flow_log_id=TEST_FLOW_LOG_ID)

    assert utils.database_execute_query(instance.db_connector, SQL_COUNT_ROWS.format(
        table_name=instance.db_table_name)) == expected_db_count


@patch('aws_bucket.AWSLogsBucket.__init__')
def test_AWSVPCFlowBucket_get_vpc_prefix(mock_logs_bucket):
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket)

    expected_vpc_prefix = utils.TEST_FULL_PREFIX + utils.TEST_CREATION_DATE + '/' + utils.TEST_ACCOUNT_ID + '_vpcflowlogs_' + utils.TEST_REGION + '_' + TEST_FLOW_LOG_ID

    with patch('aws_bucket.AWSLogsBucket.get_full_prefix', return_value=utils.TEST_FULL_PREFIX):
        vpc_prefix = instance.get_vpc_prefix(utils.TEST_ACCOUNT_ID, utils.TEST_REGION,
                                             utils.TEST_CREATION_DATE, TEST_FLOW_LOG_ID)
    assert expected_vpc_prefix == vpc_prefix


@pytest.mark.skip("Not implemented yet")
def test_AWSVPCFlowBucket_build_s3_filter_args():
    pass


@pytest.mark.skip("Not implemented yet")
def test_AWSVPCFlowBucket_iter_files_in_bucket():
    pass


@patch('aws_bucket.AWSLogsBucket.__init__', side_effect=aws_bucket.AWSLogsBucket.__init__)
def test_AWSVPCFlowBucket_mark_complete(mock_logs_bucket, custom_database):
    utils.database_execute_script(custom_database, TEST_EMPTY_TABLE_SCHEMA)

    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket, bucket=utils.TEST_BUCKET)

    instance.reparse = True
    with patch('vpcflow.AWSVPCFlowBucket.already_processed', return_value = True), \
            patch('aws_bucket.aws_tools.debug') as mock_debug:
        instance.mark_complete(aws_account_id=utils.TEST_ACCOUNT_ID, aws_region=utils.TEST_REGION,
                               log_file={'Key': TEST_LOG_KEY}, flow_log_id=TEST_FLOW_LOG_ID)
        mock_debug.assert_called_once_with(f'+++ File already marked complete, but reparse flag set: {TEST_LOG_KEY}',2)

    instance.reparse = False

    instance.db_connector = custom_database
    instance.db_cursor = instance.db_connector.cursor()
    instance.db_table_name = TEST_TABLE_NAME

    assert utils.database_execute_query(instance.db_connector,
                                        SQL_COUNT_ROWS.format(table_name=instance.db_table_name)) == 0

    with patch('aws_bucket.AWSLogsBucket.get_creation_date', return_value=utils.TEST_CREATION_DATE):
        instance.mark_complete(aws_account_id=utils.TEST_ACCOUNT_ID, aws_region=utils.TEST_REGION,
                             log_file={'Key': TEST_LOG_KEY}, flow_log_id=TEST_FLOW_LOG_ID)

    assert utils.database_execute_query(instance.db_connector,
                                        SQL_COUNT_ROWS.format(table_name=instance.db_table_name)) == 1

    row = utils.database_execute_query(instance.db_connector, SQL_GET_ROW.format(table_name=instance.db_table_name))
    assert row[0] == f"{utils.TEST_BUCKET}/"
    assert row[1] == utils.TEST_ACCOUNT_ID
    assert row[2] == utils.TEST_REGION
    assert row[3] == TEST_FLOW_LOG_ID
    assert row[4] == TEST_LOG_KEY
    assert row[5] == utils.TEST_CREATION_DATE


@patch('aws_bucket.aws_tools.debug')
@patch('aws_bucket.AWSLogsBucket.__init__', side_effect=aws_bucket.AWSLogsBucket.__init__)
def test_AWSVPCFlowBucket_mark_complete_ko(mock_logs_bucket, mock_debug, custom_database):
    instance = utils.get_mocked_bucket(class_=vpcflow.AWSVPCFlowBucket, reparse=False)

    instance.db_connector = custom_database
    mocked_cursor = MagicMock()
    mocked_cursor.execute.side_effect = Exception
    instance.db_cursor = mocked_cursor

    instance.mark_complete(aws_account_id=utils.TEST_ACCOUNT_ID, aws_region=utils.TEST_REGION,
                           log_file={'Key': TEST_LOG_KEY}, flow_log_id=TEST_FLOW_LOG_ID)

    mock_debug.assert_any_call(f"+++ Error marking log {TEST_LOG_KEY} as completed: ", 2)