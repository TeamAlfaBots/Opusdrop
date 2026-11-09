import hashlib, hmac, secrets

def new_file_id(): return secrets.token_urlsafe(18)
def new_delete_token(): return secrets.token_urlsafe(32)
def token_hash(token:str): return hashlib.sha256(token.encode()).hexdigest()
def verify_token(token:str, expected:str): return hmac.compare_digest(token_hash(token), expected)
