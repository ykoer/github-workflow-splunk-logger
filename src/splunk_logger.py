#!/usr/bin/env python3

import os
import sys
import json
import time
import requests
from github import Github

def get_input(name, required=False, default=None):
    """Gets the input value from environment variables"""
    env_name = f"INPUT_{name.upper()}"
    value = os.environ.get(env_name)
    
    if required and not value:
        print(f"::error::Input '{name}' is required but not provided")
        sys.exit(1)
    
    return value if value is not None else default

def log_info(message):
    """Log an info message"""
    print(f"::info::{message}")

def log_error(message):
    """Log an error message"""
    print(f"::error::{message}")

def send_to_splunk(splunk_url, token, event_data: dict, ssl_verify: bool, timeout: str, max_retries: str):
    """Send data to Splunk HTTP Event Collector"""
    splunk_hec_endpoint = f"{splunk_url}/services/collector"
    
    headers = {
        'Authorization': f"Splunk {token}",
        'Content-Type': 'application/json'
    }
    
    attempts = 0
    
    while attempts < int(max_retries):
        try:
            response = requests.post(
                splunk_hec_endpoint,
                json=event_data,
                headers=headers,
                verify=ssl_verify == 'true',
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

def main():
    try:
        # Get inputs
        splunk_url = get_input('splunk_url', required=True)
        splunk_token = get_input('splunk_token', required=True)
        # workflow_name = get_input('workflow_name', required=True)
        run_id = get_input('run_id') or os.environ.get('GITHUB_RUN_ID')
        index = get_input('index', default='github_workflows')
        source_type = get_input('source_type', default='github:workflow:logs')
        ssl_verify = get_input('ssl_verify', default='true')
        include_job_steps = get_input('include_job_steps', default='true')
        timeout = get_input('timeout', default='30')
        max_retries = get_input('max_retries', default='3')

        # Get GitHub token
        github_token = os.environ.get('GITHUB_TOKEN')
        if not github_token:
            raise Exception("GITHUB_TOKEN is required. Make sure to set it in your workflow.")
        
        # Initialize GitHub client
        g = Github(github_token)
        
        # Get repository information
        github_repository = os.environ.get('GITHUB_REPOSITORY')
        owner_name, repo_name = github_repository.split('/')
        repo = g.get_repo(github_repository)
        
        # Fetch workflow run information
        log_info(f"Fetching logs for run ID {run_id}")
        workflow_run = repo.get_workflow_run(int(run_id))
        
        # Prepare event data for Splunk
        workflow_event = {
            "event": {
                "workflow": {
                    "id": workflow_run.id,
                    # "name": workflow_name,
                    "name":  workflow_run.name,
                    "status": workflow_run.status,
                    "conclusion": workflow_run.conclusion,
                    "created_at": workflow_run.created_at.isoformat(),
                    "updated_at": workflow_run.updated_at.isoformat(),
                    "url": workflow_run.url,
                    "html_url": workflow_run.html_url
                },
                "repository": {
                    "owner": owner_name,
                    "name": repo_name,
                    "full_name": github_repository
                },
                "github_context": {
                    "workflow": os.environ.get('GITHUB_WORKFLOW'),
                    "run_id": os.environ.get('GITHUB_RUN_ID'),
                    "run_number": os.environ.get('GITHUB_RUN_NUMBER'),
                    "actor": os.environ.get('GITHUB_ACTOR'),
                    "repository": os.environ.get('GITHUB_REPOSITORY'),
                    "event_name": os.environ.get('GITHUB_EVENT_NAME'),
                    "ref": os.environ.get('GITHUB_REF'),
                    "sha": os.environ.get('GITHUB_SHA')
                }
            },
            "sourcetype": source_type,
            "source": f"github:{owner_name}/{repo_name}:workflow:{workflow_run.name}"
        }

        if index:
            workflow_event["index"] = index
        
        # Send workflow data to Splunk
        send_to_splunk(splunk_url, splunk_token, workflow_event, ssl_verify, timeout, max_retries)
        log_info("Successfully sent workflow information to Splunk")
        
        # Fetch and send job logs if requested
        if include_job_steps == 'true':
            jobs = workflow_run.jobs()
            
            for job in jobs:
                log_info(f"Fetching logs for job: {job.name} ({job.id})")
                
                try:
                    log_url = job.logs_url()
                    log_response = requests.get(log_url, headers={'Authorization': f'token {github_token}'})
                    
                    if log_response.status_code == 200:
                        job_logs = log_response.text
                    else:
                        job_logs = f"Could not fetch logs: {log_response.status_code}"
                except Exception as e:
                    job_logs = f"Error fetching logs: {str(e)}"
                
                # Create event for job logs
                job_log_event = {
                    "event": {
                        "job_id": job.id,
                        "job_name": job.name,
                        "job_status": job.conclusion or job.status,
                        "workflow_name": workflow_run.name,
                        "workflow_run_id": workflow_run.id,
                        "repository": {
                            "owner": owner_name,
                            "name": repo_name,
                            "full_name": github_repository
                        },
                        "logs": job_logs
                    },
                    "sourcetype": f"{source_type}:job",
                    "source": f"github:{owner_name}/{repo_name}:workflow:{workflow_run.name}:job:{job.name}",
                    "index": index
                }
                
                # Send job log to Splunk
                send_to_splunk(splunk_url, splunk_token, job_log_event, ssl_verify, timeout, max_retries)
                log_info(f"Successfully sent logs for job: {job.name}")
        
        log_info("Action completed successfully")
        
    except Exception as e:
        log_error(f"Action failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()