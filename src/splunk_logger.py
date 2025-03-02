#!/usr/bin/env python3

import argparse
import json
import requests
import os
import sys
import time
from github import Github

def get_input(name: str, required: bool=False, default: str=None):
    """Gets the input value from environment variables"""
    env_name = f"INPUT_{name.upper()}"
    value = os.environ.get(env_name)
    
    if required and not value:
        print(f"::error::Input '{name}' is required but not provided")
        sys.exit(1)
    
    return value if value is not None else default

def log_info(message: str):
    """Log an info message"""
    print(f"::info::{message}")

def log_error(message: str):
    """Log an error message"""
    print(f"::error::{message}")

def send_to_splunk(splunk_url: str, token: str, event_data: dict, ssl_verify: bool, timeout: str, max_retries: str, debug: bool = False):
    """Send data to Splunk HTTP Event Collector"""
    splunk_hec_endpoint = f"{splunk_url}/services/collector"
    
    headers = {
        'Authorization': f"Splunk {token}",
        'Content-Type': 'application/json'
    }
    
    attempts = 0

    if not debug:
        while attempts < int(max_retries):
            try:
                response = requests.post(
                    splunk_hec_endpoint,
                    json=event_data,
                    headers=headers,
                    verify=ssl_verify == True,
                    timeout=float(timeout)
                )
                
                if response.status_code == 200:
                    return
                else:
                    raise Exception(f"Splunk HEC responded with status code {response.status_code}: {response.text}")
            except Exception as e:
                attempts += 1
                if attempts >= int(max_retries):
                    raise e
                
                # Exponential backoff
                delay = 2 ** attempts
                log_info(f"Attempt {attempts} failed. Retrying in {delay} seconds...")
                time.sleep(delay)
    else:
        print(f"Attempting to send data to Splunk HEC to {splunk_hec_endpoint}")
        print(json.dumps(event_data, indent=4))

def fetch_and_send_logs(splunk_url: str, splunk_token: str, github_token: str, repo_name: str, run_id: int, index: str, source_type: str, ssl_verify: bool, 
                        include_job_steps: bool, timeout: int, max_retries: int, debug: bool = False):
    """Fetch workflow logs and send them to Splunk"""
    g = Github(github_token)
    repo = g.get_repo(repo_name)
    workflow_run = repo.get_workflow_run(int(run_id))

    log_info(f"Fetching logs for run ID {run_id}")

    event_data = {
        "event": {
            "workflow": {
                "id": workflow_run.id,
                "name": workflow_run.name,
                "status": workflow_run.status,
                "conclusion": workflow_run.conclusion,
                "created_at": workflow_run.created_at.isoformat(),
                "updated_at": workflow_run.updated_at.isoformat(),
                "url": workflow_run.url,
                "html_url": workflow_run.html_url
            },
            "repository": {
                "owner": repo.owner.login,
                "name": repo.name,
                "full_name": repo.full_name
            }
        },
        "sourcetype": source_type,
        "source": f"github:{repo.owner.login}/{repo.name}:workflow:{workflow_run.name}"
    }

    if index:
        event_data["index"] = index

    send_to_splunk(splunk_url, splunk_token, event_data, ssl_verify, timeout, max_retries, debug)
    log_info("Successfully sent workflow information to Splunk")

    if include_job_steps:
        jobs = workflow_run.jobs()
        for job in jobs:
            log_info(f"Fetching logs for job: {job.name} ({job.id})")
            job_logs = f"Logs unavailable for job: {job.name}"

            try:
                log_url = job.logs_url()
                log_response = requests.get(log_url, headers={'Authorization': f'token {github_token}'})
                if log_response.status_code == 200:
                    job_logs = log_response.text
            except Exception as e:
                job_logs = f"Error fetching logs: {str(e)}"

            job_event = {
                "event": {
                    "job_id": job.id,
                    "job_name": job.name,
                    "job_status": job.conclusion or job.status,
                    "job_created_at": job.created_at.isoformat(),
                    "job_completed_at": job.completed_at.isoformat(),
                    "job.status": job.status,
                    "workflow_name": workflow_run.name,
                    "workflow_run_id": workflow_run.id,
                    "logs": job_logs
                },
                "sourcetype": f"{source_type}:job",
                "source": f"github:{repo.owner.login}/{repo.name}:workflow:{workflow_run.name}:job:{job.name}"
            }

            if index:
                job_event["index"] = index

            send_to_splunk(splunk_url, splunk_token, job_event, ssl_verify, timeout, max_retries, debug)
            log_info(f"Successfully sent logs for job: {job.name}")


def main():
    # Get inputs
    splunk_url = get_input('splunk_url', required=True)
    splunk_token = get_input('splunk_token', required=True)
    run_id = int(get_input('run_id') or os.environ.get('GITHUB_RUN_ID'))
    index = get_input('index', default='github_workflows')
    source_type = get_input('source_type', default='github:workflow:logs')
    ssl_verify = get_input('ssl_verify', default='true').lower() == 'true'
    include_job_steps = get_input('include_job_steps', default='true').lower() == 'true'
    timeout = int(get_input('timeout', default='30'))
    max_retries = int(get_input('max_retries', default='3'))
    debug = get_input('debug', default='false').lower() == 'true'

    # Get GitHub token
    github_token = os.environ.get('GITHUB_TOKEN')
    if not github_token:
        raise Exception("GITHUB_TOKEN is required. Make sure to set it in your workflow.")
    
    # Get repository information from environment variables. This assumes the repository is in the format 'owner/repo'.
    github_repo_name = os.environ.get('GITHUB_REPOSITORY')

    try:
        fetch_and_send_logs(splunk_url, splunk_token, github_token, github_repo_name, run_id, index, source_type, ssl_verify, include_job_steps, timeout, max_retries, debug)
        log_info("Script completed successfully")
    except Exception as e:
        log_error(f"Script failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
