import json
import secrets
import base64
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
import httpx
import asyncio
from redis_client import add_key_value_redis, get_value_redis, delete_key_redis
from integrations.integration_item import IntegrationItem
import requests
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)

CLIENT_ID = 'f077059f-d12f-4b41-9224-ff982d4ea668'
CLIENT_SECRET = '125696f1-36d6-4f1e-a944-d411213a6bd8'
REDIRECT_URI = 'http://localhost:8000/integrations/hubspot/oauth2callback'
authorization_url = 'https://app-na2.hubspot.com/oauth/authorize?client_id=f077059f-d12f-4b41-9224-ff982d4ea668&redirect_uri=http://localhost:8000/integrations/hubspot/oauth2callback&scope=oauth%20crm.objects.contacts.read'

encoded_client_id_secret = base64.b64encode(f'{CLIENT_ID}:{CLIENT_SECRET}'.encode()).decode()

async def authorize_hubspot(user_id, org_id):
    state_data = {
        'state': secrets.token_urlsafe(32),
        'user_id': user_id,
        'org_id': org_id
    }
    encoded_state = json.dumps(state_data)
    await add_key_value_redis(f'hubspot_state:{org_id}:{user_id}', encoded_state, expire=600)

    return f'{authorization_url}&state={encoded_state}'

async def oauth2callback_hubspot(request: Request):
    if request.query_params.get('error'):
        raise HTTPException(status_code=400, detail=request.query_params.get('error_description'))
    code = request.query_params.get('code')
    encoded_state = request.query_params.get('state')
    state_data = json.loads(encoded_state)

    original_state = state_data.get('state')
    user_id = state_data.get('user_id')
    org_id = state_data.get('org_id')

    saved_state = await get_value_redis(f'hubspot_state:{org_id}:{user_id}')

    if not saved_state or original_state != json.loads(saved_state).get('state'):
        raise HTTPException(status_code=400, detail='State does not match.')

    async with httpx.AsyncClient() as client:
        response, _ = await asyncio.gather(
            client.post(
                'https://api.hubapi.com/oauth/v1/token',
                data={
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': REDIRECT_URI,
                    'client_id': CLIENT_ID,
                    'client_secret': CLIENT_SECRET,
                },
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                }
            ),
            delete_key_redis(f'hubspot_state:{org_id}:{user_id}'),
        )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail='Failed to fetch access token.')

    await add_key_value_redis(f'hubspot_credentials:{org_id}:{user_id}', json.dumps(response.json()), expire=600)
    
    close_window_script = """
    <html>
        <script>
            window.close();
        </script>
    </html>
    """
    return HTMLResponse(content=close_window_script)

async def get_hubspot_credentials(user_id, org_id):
    credentials = await get_value_redis(f'hubspot_credentials:{org_id}:{user_id}')
    if not credentials:
        raise HTTPException(status_code=400, detail='No credentials found.')
    credentials = json.loads(credentials)
    await delete_key_redis(f'hubspot_credentials:{org_id}:{user_id}')

    return credentials

async def create_integration_item_metadata_object(response_json):
    """Creates an integration metadata object from the response"""
    integration_item_metadata = IntegrationItem(
        id=response_json.get('id'),
        name=response_json.get('properties', {}).get('name', {}).get('value', 'Unnamed'),
        type=response_json.get('type', 'Unknown'),
        parent_id=response_json.get('parent', {}).get('id'),
        parent_path_or_name=response_json.get('parent', {}).get('name')
    )
    return integration_item_metadata

async def get_items_hubspot(credentials) -> list[IntegrationItem]:
    """Aggregates all metadata relevant for a HubSpot integration"""
    credentials = json.loads(credentials)
    access_token = credentials.get("access_token")
    logging.debug(f"Access Token: {access_token}")
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    url = 'https://api.hubapi.com/crm/v3/objects/contacts'
    response = requests.get(url, headers=headers)

    logging.debug(f"Response Status Code: {response.status_code}")
    logging.debug(f"Response Content: {response.content}")

    if response.status_code == 200:
        results = response.json().get('results', [])
        list_of_integration_item_metadata = []
        for result in results:
            list_of_integration_item_metadata.append(
                await create_integration_item_metadata_object(result)
            )
        return list_of_integration_item_metadata
    else:
        raise HTTPException(status_code=response.status_code, detail='Failed to fetch items from HubSpot')