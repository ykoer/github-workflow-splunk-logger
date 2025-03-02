import os
import click
import functools
from splunk_logger import fetch_and_send_logs


def env_or_required(key):
    """Fetch value from environment variable or mark as required."""
    value = os.getenv(key)
    if value is None:
        raise click.MissingParameter(f"Missing required parameter: {key.replace('_', '-').lower()}")
    return value

def process_workflow_run(config: dict, run_id: int):
    """Process a single GitHub Workflow Run ID."""
    click.echo(f"Processing Workflow Run ID: {run_id}")
    fetch_and_send_logs(
        config['splunk_url'],
        config['splunk_token'],
        config['github_token'],
        config['repo'],
        run_id,
        None, # index
        config['source_type'],
        config['ssl_verify'], 
        config['include_job_steps'],
        config['timeout'], 
        config['max_retries'], 
        config['debug']
    )
    click.echo(f"Workflow Run ID {run_id} processed.")

def common_options(f):
    """Decorator to add common options to a command."""
    options = [
        click.option("--splunk-url", default=lambda: env_or_required("SPLUNK_URL"), required=True, help="Splunk HEC URL"),
        click.option("--splunk-token", default=lambda: env_or_required("SPLUNK_TOKEN"), required=True, help="Splunk HEC Token"),
        click.option("--github-token", default=lambda: env_or_required("GITHUB_TOKEN"), required=True, help="GitHub Token"),
        click.option("--repo", default=lambda: env_or_required("GITHUB_REPOSITORY"), required=True, help="GitHub Repository (e.g., owner/repo)"),
        click.option("--source-type", default="github:workflow:logs", help="Splunk Source Type"),
        click.option("--ssl-verify", type=bool, default=True, help="Verify SSL"),
        click.option("--include-job-steps", type=bool, default=True, help="Include Job Logs"),
        click.option("--timeout", default="30", help="Request Timeout"),
        click.option("--max-retries", default="3", help="Max Retry Attempts"),
        click.option("--debug", is_flag=True, help="Enable debugging to print the Splunk event without actually sending it")
    ]
    return functools.reduce(lambda x, opt: opt(x), options, f)

@click.group()
def cli():
    """CLI tool for sending GitHub Workflow logs to Splunk."""
    pass


@cli.command("process-workflow-run", help="Process a single GitHub Workflow Run ID.")
@click.option("--run-id", "-r", required=True, type=int, help="GitHub Workflow Run ID")
@common_options
def process_workflow_run_cmd(run_id, **kwargs):
    """Process a single GitHub Workflow Run ID."""
    process_workflow_run(kwargs, run_id)


@cli.command("process-workflow-run-batch", help="Process a batch of GitHub Workflow Run IDs from a file.")
@click.option("--workflow-ids-file", "-f", required=True, help="File containing GitHub Workflow Run IDs")
@click.option("--count", "-c", required=False, type=int, help="Number of Workflow Run IDs to process")
@common_options
def process_workflow_run_batch_cmd(workflow_ids_file: str, count: int, **kwargs):
    """Process a batch of GitHub Workflow Run IDs from a file."""
    # Read the file containing Workflow IDs
    try:
        with open(workflow_ids_file, 'r') as file:
            all_workflow_ids = file.readlines()
    except FileNotFoundError:
        click.echo(f"Error: File '{workflow_ids_file}' not found.")
        return

    # Clean up the IDs and ensure they are unique
    all_workflow_ids = [line.strip() for line in all_workflow_ids]

    # If count is provided, limit the number of rows to process
    workflow_ids = all_workflow_ids[:count] if count else all_workflow_ids

    # Process the workflows, remove the id from workflow_ids_file
    processed_ids = []
    for workflow_run_id in workflow_ids:
        process_workflow_run(kwargs, workflow_run_id)
        processed_ids.append(workflow_run_id)
    
    unprocessed_ids = c = [item for item in all_workflow_ids if item not in processed_ids]

    # Write back remaining unprocessed IDs to the original file
    with open(workflow_ids_file, 'w') as file:
        for id in unprocessed_ids:
            file.write(f"{id}\n")


if __name__ == "__main__":
    cli()