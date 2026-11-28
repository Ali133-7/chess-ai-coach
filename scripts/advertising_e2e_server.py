"""Disposable HTTPS origin for intercepted AdSense browser tests. No real ads."""
import ipaddress,os,sys,tempfile,asyncio
from datetime import datetime,timedelta,timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

if os.name=='nt':asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
temporary=tempfile.TemporaryDirectory(prefix='chess-ad-security-tests-');root=Path(temporary.name)
os.environ.update(STUDIO_DB=str(root/'studio.sqlite3'),CHESS_KNOWLEDGE_DB=str(root/'knowledge.sqlite3'),STUDIO_BASE_URL='https://ads.example.net:18025',STUDIO_COOKIE_SECURE='true',CONTROL_PRIVATE_DIR=str(root/'private'),DATABASE_PATH=str(root/'legacy.sqlite3'),CHESS_LIBRARY_DB=str(root/'no-catalogue.sqlite3'),TEACHER_PROVIDERS_FILE=str(root/'no-provider.json'),TEACHER_KEY_FILE=str(root/'no-key'))
key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Disposable advertising test origin')]);now=datetime.now(timezone.utc)
certificate=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('ads.example.net'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
(root/'tls.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));(root/'tls.key').chmod(0o600)
(root/'tls.crt').write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
from studio.app import app,start
from studio import core
import studio.app as app_module
original_limit=app_module.ratelimit
def fixture_limit(key,limit=6,window=900):return original_limit(key,limit*20 if key.startswith(('login:','login-ip:')) else limit,window)
app_module.ratelimit=fixture_limit
start()
with core.connection() as db:
 for index in range(2):db.execute('INSERT INTO users(email,pass_hash,role,created_at,chess_username) VALUES(?,?,?,?,?)',(f'ads{index}@example.test',core.passhash('disposable-ad-test-password'),'admin' if index else 'user',core.now(),'ads_fixture'+str(index)))
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=18025,access_log=False,log_level='warning',ssl_keyfile=str(root/'tls.key'),ssl_certfile=str(root/'tls.crt'))
