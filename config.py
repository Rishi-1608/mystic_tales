from datetime import timedelta


# Flask configuration
class Config:
    SECRET_KEY = 'your_secret_key_here'
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = True
PERMANENT_SESSION_LIFETIME = timedelta(hours=1)