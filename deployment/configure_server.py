"""First-boot EC2 setup; executes inside the instance, never CloudShell."""
import json,os,secrets,subprocess,pathlib,urllib.request
import boto3,MySQLdb
from MySQLdb.constants import CLIENT
from werkzeug.security import generate_password_hash
root=pathlib.Path('/opt/campus');cfg=json.load(open('/etc/campus/bootstrap.json'))
sm=boto3.client('secretsmanager',region_name=cfg['region'])
def secret(arn):return json.loads(sm.get_secret_value(SecretId=arn)['SecretString'])
master=secret(cfg['master_secret']);appdb=secret(cfg['app_secret']);portal=secret(cfg['portal_secret'])
subprocess.run(['chgrp','campus','/etc/campus'],check=True)
pathlib.Path('/etc/campus').chmod(0o750)
ca='/etc/campus/rds-global-bundle.pem'
urllib.request.urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem',ca)
db=MySQLdb.connect(host=cfg['database_host'],user=master['username'],passwd=master['password'],db='institute_db',ssl={'ca':ca},client_flag=CLIENT.MULTI_STATEMENTS,charset='utf8mb4')
c=db.cursor()
marker=root/'.database-imported'
if not marker.exists():
    c.execute((root/'deployment'/'database.sql').read_bytes())
    while c.nextset():pass
    db.commit();marker.touch()
c.execute("CREATE USER IF NOT EXISTS 'campusapp'@'%%' IDENTIFIED BY %s",(appdb['password'],))
c.execute("ALTER USER 'campusapp'@'%%' IDENTIFIED BY %s REQUIRE SSL",(appdb['password'],))
c.execute("GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,INDEX,REFERENCES ON institute_db.* TO 'campusapp'@'%'")
hashvalue=generate_password_hash(portal['password'])
for table in ('student_login','teacher_login','institute_login'):c.execute(f'UPDATE {table} SET password=%s',(hashvalue,))
c.execute("UPDATE subject_notes SET notes_link=REPLACE(notes_link,'http://127.0.0.1:5000','')")
db.commit();db.close()
envfile=pathlib.Path('/etc/campus/campus.env')
sessionkey=secrets.token_hex(32)
if envfile.exists():
    for line in envfile.read_text().splitlines():
        if line.startswith('SECRET_KEY='):sessionkey=line.split('=',1)[1]
env={'MYSQL_HOST':cfg['database_host'],'MYSQL_USER':'campusapp','MYSQL_PASSWORD':appdb['password'],'MYSQL_DB':'institute_db','MYSQL_SSL_CA':ca,'SECRET_KEY':sessionkey,'COOKIE_SECURE':'1','AWS_REGION':cfg['region'],'S3_BUCKET':cfg['bucket'],'SNS_TOPIC_ARN':cfg['sns_topic'],'PORTAL_PUBLIC_URL':cfg['portal_url']}
envfile.write_text(''.join(f'{k}={v}\n' for k,v in env.items()));envfile.chmod(0o600)
# Caddy supplies trusted HTTPS directly on EC2 without CloudFront.
urllib.request.urlretrieve('https://caddyserver.com/api/download?os=linux&arch=amd64','/usr/local/bin/caddy')
pathlib.Path('/usr/local/bin/caddy').chmod(0o755)
subprocess.run(['useradd','--system','--home-dir','/var/lib/caddy','--create-home','--shell','/sbin/nologin','caddy'],check=False)
pathlib.Path('/etc/caddy').mkdir(exist_ok=True)
domain=cfg['portal_url'].removeprefix('https://')
pathlib.Path('/etc/caddy/Caddyfile').write_text(domain + ' {\n    request_body {\n        max_size 20MB\n    }\n    reverse_proxy 127.0.0.1:8000\n}\n')
pathlib.Path('/etc/systemd/system/caddy.service').write_text("""[Unit]
Description=Campus HTTPS
After=network-online.target campus.service
Wants=network-online.target
[Service]
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
Restart=on-failure
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
""")
pathlib.Path('/etc/systemd/system/campus.service').write_text('''[Unit]
Description=DSCE campus Flask portal
After=network-online.target
[Service]
User=campus
Group=campus
WorkingDirectory=/opt/campus
EnvironmentFile=/etc/campus/campus.env
ExecStart=/opt/campus/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 --timeout 60 app:app
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
''')
pathlib.Path('/etc/systemd/system/campus-notifications.service').write_text('''[Unit]
Description=Create campus reminders and publish SNS digest
After=campus.service
[Service]
Type=oneshot
User=campus
Group=campus
WorkingDirectory=/opt/campus
EnvironmentFile=/etc/campus/campus.env
ExecStart=/opt/campus/.venv/bin/python -m flask --app app run-notifications
''')
pathlib.Path('/etc/systemd/system/campus-notifications.timer').write_text('''[Unit]
Description=Daily campus reminders at 09:00 India time
[Timer]
OnCalendar=*-*-* 03:30:00 UTC
Persistent=true
RandomizedDelaySec=30
[Install]
WantedBy=timers.target
''')
subprocess.run(['chown','-R','campus:campus','/opt/campus'],check=True)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['/usr/local/bin/caddy','validate','--config','/etc/caddy/Caddyfile','--adapter','caddyfile'],check=True)
subprocess.run(['systemctl','enable','--now','campus.service','caddy.service','campus-notifications.timer'],check=True)
subprocess.run(['systemctl','restart','caddy.service','campus.service'],check=True)
print('Campus services configured successfully')
