import azure.functions as func
from azure.storage.blob import BlobServiceClient
import datetime
import json
import logging
import requests, json
import os
import tempfile


app = func.FunctionApp()

@app.route(route="get_and_insert_data", auth_level=func.AuthLevel.FUNCTION)
def get_and_insert_data(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    run_id = req.params.get('parent_run_id')
    experiment_id = req.params.get('experiment_id')

    if not run_id or not experiment_id:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            if not run_id:
                run_id = req_body.get('parent_run_id')
            if not experiment_id:
                experiment_id = req_body.get('experiment_id')

    if run_id and experiment_id:
        raw_data = get_data_from_aml(experiment_id, run_id)
        return func.HttpResponse(f"Get {run_id} aml pipeline and store to {raw_data}")
    else:
        return func.HttpResponse(
             "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response.",
             status_code=200
        )

def get_data_from_aml(experiment_name, parent_run_id):
    tenant_id = os.getenv("TENANT_ID")
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")

    # Get the bearer token
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/token"
    token_data = {
        "grant_type": "client_credentials",
        "resource": "https://management.azure.com/",
        "client_id": client_id,
        "client_secret": client_secret
    }

    token_response = requests.post(token_url, data=token_data)
    token_response.raise_for_status()  # Raise an exception for HTTP errors
    token = token_response.json().get("access_token")

    aml_location = os.environ["AML_LOCATION"]
    subscription_id = os.environ["SUBSCRIPTION_ID"]
    resource_group = os.environ["RESOURCE_GROUP"]
    workspace_name = os.environ["WORKSPACE_NAME"]

    # Use the bearer token in the headers
    url = f"https://{aml_location}.api.azureml.ms/history/v1.0/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.MachineLearningServices/workspaces/{workspace_name}/experiments/{experiment_name}/runs?api-version=2023-10-01"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    logging.info(f"Requesting data from {url}")
    response = requests.get(url, headers=headers)
    response.raise_for_status()  # Raise an exception for HTTP errors

    # Parse response to JSON
    response_json = response.json()
    # Get the parentRunId to filter from the command-line arguments
    parent_run_id_to_filter = parent_run_id
    # Collect filtered responses
    filtered_responses = []

    logging.info(f"Parent run id to filter: {parent_run_id_to_filter}")
    # Checkout response_json for all response data and filter out the required data
    for item in response_json["value"]:
        if item.get("parentRunId") == parent_run_id_to_filter or item.get("runId") == parent_run_id_to_filter:
            dataContainerId = item.get("dataContainerId")
            # Filter the response content
            filtered_response = {
                "name": item.get("name"),
                "displayName": item.get("displayName"),
                "runType": item.get("runType"),
                "runId": item.get("runId"),
                "dataContainerId": item.get("dataContainerId"),
                "custom_rawLogArtifactsLocation": f"azureml/ExperimentRun/{dataContainerId}/",
                "experimentId": item.get("experimentId"),
                "parentRunId": item.get("parentRunId"),
                "status": item.get("status"),
                "createdUtc": item.get("createdUtc"),
                "startTimeUtc": item.get("startTimeUtc"),
                "endTimeUtc": item.get("endTimeUtc"),
                "computeDuration": item.get("computeDuration"),
                "compute": item.get("compute"),
                "tags": item.get("tags"),
                "properties": item.get("properties"),
                "parameters": item.get("parameters")
            }
            filtered_responses.append(filtered_response)

    temp_dir = tempfile.gettempdir()
    temp_file_path = os.path.join(temp_dir, f'{parent_run_id}.json')
    with open(temp_file_path, 'w') as json_file:
        json.dump(filtered_responses, json_file, indent=4)

    # Verify the file is saved in the temporary directory
    files_in_temp = os.listdir(temp_dir)
    logging.info(f"Files in temp directory: {files_in_temp}")
    # Print the path of the saved file
    logging.info(f"Filtered responses saved to {temp_file_path}")

    blob_name = os.getenv("JSON_STORE_BLOB_NAME")
    blob_key = os.getenv("JSON_STORE_BLOB_KEY")
    
    # Store JSON file to azure blob storage
    blob_service_client = BlobServiceClient.from_connection_string(f"DefaultEndpointsProtocol=https;AccountName={blob_name};AccountKey={blob_key};EndpointSuffix=core.windows.net")
    blob_client = blob_service_client.get_blob_client(container="monitoring", blob=f"{parent_run_id}.json")
    with open(temp_file_path, 'rb') as data:
        blob_client.upload_blob(data, overwrite=True)

    file_blob_location = f"{blob_name}.blob.core.windows.net/monitoring/{parent_run_id}.json"
    logging.info(f"Filtered responses saved to {file_blob_location}")
    return file_blob_location
    