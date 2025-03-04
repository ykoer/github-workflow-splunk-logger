import pytest
from unittest.mock import MagicMock, patch
import os
from datetime import datetime
import requests
import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from src.splunk_logger import main, send_to_splunk

@pytest.fixture
def mock_env_vars():
    """Fixture to set required environment variables"""
    env_vars = {
        'INPUT_SPLUNK_URL': 'https://splunk.example.com',
        'INPUT_SPLUNK_TOKEN': 'dummy-token',
        'INPUT_WORKFLOW_NAME': 'test-workflow',
        'INPUT_RUN_ID': '12345',
        'GITHUB_TOKEN': 'github-token',
        'GITHUB_REPOSITORY': 'owner/repo',
        'GITHUB_WORKFLOW': 'test-workflow',
        'GITHUB_RUN_ID': '12345',
        'GITHUB_RUN_NUMBER': '1',
        'GITHUB_ACTOR': 'test-user',
        'GITHUB_EVENT_NAME': 'push',
        'GITHUB_REF': 'refs/heads/main',
        'GITHUB_SHA': 'abc123'
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars

@pytest.fixture
def mock_github_client():
    """Fixture to mock the Github client"""
    mock_job1 = MagicMock()
    mock_job1.name = 'test-job1'
    mock_job1.id = 98765
    mock_job1.status = 'completed'
    mock_job1.conclusion = 'success'
    mock_job1.logs_url.return_value = 'https://api.github.com/logs/test'

    mock_job2 = MagicMock()
    mock_job2.name = 'test-job2'
    mock_job2.id = 98766
    mock_job2.status = 'completed'
    mock_job2.conclusion = 'success'
    mock_job2.logs_url.return_value = 'https://api.github.com/logs/test'

    mock_workflow_run = MagicMock()
    mock_workflow_run.id = 12345
    mock_workflow_run.name = 'test-workflow'
    mock_workflow_run.status = 'completed'
    mock_workflow_run.conclusion = 'success'
    mock_workflow_run.created_at = datetime(2024, 1, 1, 12, 0)
    mock_workflow_run.updated_at = datetime(2024, 1, 1, 12, 30)
    mock_workflow_run.url = 'https://api.github.com/workflow/12345'
    mock_workflow_run.html_url = 'https://github.com/owner/repo/actions/runs/12345'
    mock_workflow_run.jobs.return_value = [mock_job1, mock_job2]
    mock_workflow_run.head_sha = '1ffe17be746af28a69c3e4d3919088fd2a125740'
                                  
    mock_repo = MagicMock()
    mock_repo.owner.login = 'owner'
    mock_repo.name = 'repo'
    mock_repo.full_name = 'owner/repo'

    mock_repo.get_workflow_run.return_value = mock_workflow_run

    mock_github = MagicMock()
    mock_github.get_repo.return_value = mock_repo

    return mock_github

@pytest.fixture
def mock_splunk_requests():
    """Fixture to mock HTTP requests"""
    with patch('requests.post') as mock_post, patch('requests.get') as mock_get:
        mock_post.return_value.status_code = 200
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = 'Test job logs'
        yield {'post': mock_post, 'get': mock_get}


@patch('src.splunk_logger.Github')
@patch('requests.get') 
def test_main_success(mock_get_pull_requests, mock_github, mock_github_client, mock_splunk_requests, mock_env_vars):
    """Test successful execution of the main script"""
    
    # with patch('src.splunk_logger.Github', return_value=mock_github_client):
    #     main()

    mock_github.return_value = mock_github_client
    mock_get_pull_requests.return_value.status_code = 200
    mock_get_pull_requests.return_value.json.return_value = [
        {
            "number": 123,
            "title": "TEST-123: Create Feature A",
            "state": "open",
            "created_at": "2025-03-03T13:54:00Z",
            "updated_at": "2025-03-03T16:41:00Z",
            "merged_at": "2025-03-03T16:42:00Z",
            "closed_at": "2025-03-03T16:43:00Z",
            "merge_commit_sha": "acc94e889704fcc3e44f00455d19e0b6499e4793",
            "assignees": [
                {
                    "login": "user1"
                }
            ],
            "requested_reviewers": [
                {
                    "login": "user2"
                },
                {
                    "login": "user3"
                }
            ],
            "labels": [
                {
                    "name": "run-full-validation"
                }
            ]
        }
    ]
    main()
        
    # Check Splunk API calls
    assert mock_splunk_requests['post'].call_count == 3  # Once for workflow, once for job
    
    # Check first Splunk API request (workflow data)
    first_call_args = mock_splunk_requests['post'].call_args_list[0]
    workflow_data = first_call_args[1]['json']
    assert workflow_data['event']['workflow']['id'] == 12345
    assert workflow_data['event']['workflow']['name'] == 'test-workflow'
    assert workflow_data['event']['workflow']['status'] == 'completed'
    assert workflow_data['event']['workflow']['conclusion'] == 'success'
    assert workflow_data['event']['workflow']['created_at'] == '2024-01-01T12:00:00'
    assert workflow_data['event']['workflow']['updated_at'] == '2024-01-01T12:30:00'
    assert workflow_data['event']['workflow']['url']
    assert workflow_data['event']['workflow']['html_url']

    assert workflow_data['event']['repository']['owner'] == 'owner'
    assert workflow_data['event']['repository']['name'] == 'repo'
    assert workflow_data['event']['repository']['full_name'] == 'owner/repo'
    
    assert workflow_data['event']['pull_request']['number'] == 123
    assert workflow_data['event']['pull_request']['title'] == 'TEST-123: Create Feature A'
    assert workflow_data['event']['pull_request']['state'] == 'open'
    assert workflow_data['event']['pull_request']['created_at'] == '2025-03-03T13:54:00Z'
    assert workflow_data['event']['pull_request']['updated_at'] == '2025-03-03T16:41:00Z'
    assert workflow_data['event']['pull_request']['closed_at'] == '2025-03-03T16:43:00Z'
    assert workflow_data['event']['pull_request']['merged_at'] == '2025-03-03T16:42:00Z'
    assert workflow_data['event']['pull_request']['merge_commit_sha'] == 'acc94e889704fcc3e44f00455d19e0b6499e4793'
    assert workflow_data['event']['pull_request']['assignees'] == ['user1']
    assert workflow_data['event']['pull_request']['requested_reviewers'] == ['user2', 'user3']
    assert workflow_data['event']['pull_request']['labels'] == ['run-full-validation']

    actual_call_args, actual_call_kwargs = mock_get_pull_requests.call_args
    actual_call_args[0][0] == "https://api.github.com/repos/owner/repo/commits/1ffe17be746af28a69c3e4d3919088fd2a125740/pulls"
    actual_call_kwargs['headers'] == {'headers': {'Authorization': 'Bearer test_token'}}

    # Check second Splunk API request (job logs)
    second_call_args = mock_splunk_requests['post'].call_args_list[1]
    job_data1 = second_call_args[1]['json']
    assert job_data1['event']['job_name'] == 'test-job1'
    assert job_data1['event']['job_id'] == 98765
    assert job_data1['event']['workflow_run_id'] == 12345
    
    # Check third Splunk API request (job logs)
    third_call_args = mock_splunk_requests['post'].call_args_list[2]
    job_data2 = third_call_args[1]['json']
    assert job_data2['event']['job_name'] == 'test-job2'
    assert job_data2['event']['job_id'] == 98766
    assert job_data2['event']['workflow_run_id'] == 12345

def test_send_to_splunk_retry_success(mock_splunk_requests):
    """Test retry logic in send_to_splunk"""
    # Make first attempt fail, second succeed
    mock_splunk_requests['post'].side_effect = [
        requests.exceptions.RequestException("Connection error"),
        MagicMock(status_code=200)
    ]
    
    event_data = {"test": "data"}
    send_to_splunk(
        "https://splunk.example.com",
        "dummy-token",
        event_data,
        "true",
        "5",
        "3"
    )
    
    assert mock_splunk_requests['post'].call_count == 2

@pytest.mark.parametrize("status_code", [400, 500])
def test_send_to_splunk_error(mock_splunk_requests, status_code):
    """Test error handling in send_to_splunk"""
    mock_splunk_requests['post'].return_value.status_code = status_code
    mock_splunk_requests['post'].return_value.text = "Error message"
    
    event_data = {"test": "data"}
    with pytest.raises(Exception) as exc_info:
        send_to_splunk(
            "https://splunk.example.com",
            "dummy-token",
            event_data,
            "true",
            "5",
            "1"
        )
    
    assert f"status code {status_code}" in str(exc_info.value) 