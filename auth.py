from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

print("\n=== COPY THESE VALUES TO A SAFE PLACE ===")
print(f"GMAIL_CLIENT_ID:     {creds.client_id}")
print(f"GMAIL_CLIENT_SECRET: {creds.client_secret}")
print(f"GMAIL_REFRESH_TOKEN: {creds.refresh_token}")