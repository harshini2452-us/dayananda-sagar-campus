"""Private local or S3 notes, without embedded cloud credentials."""
import os, uuid, re
from pathlib import Path
from flask import abort, redirect, send_from_directory, session, url_for, current_app
from werkzeug.utils import secure_filename

def save_note_file(upload):
    filename=secure_filename(upload.filename)
    if not filename or filename.rsplit('.',1)[-1].lower() not in {'pdf','txt','docx'}:
        raise ValueError('Unsupported notes file')
    key='notes/'+uuid.uuid4().hex+'/'+filename
    bucket=os.environ.get('S3_BUCKET')
    if bucket:
        import boto3
        boto3.client('s3',region_name=os.environ.get('AWS_REGION','eu-north-1'),endpoint_url='https://s3.'+os.environ.get('AWS_REGION','eu-north-1')+'.amazonaws.com').upload_fileobj(upload.stream,bucket,key,ExtraArgs={'ServerSideEncryption':'AES256','ContentType':upload.mimetype or 'application/octet-stream'})
    else:
        path=Path(current_app.root_path)/'.local'/'uploads'/key
        path.parent.mkdir(parents=True,exist_ok=True);upload.save(path)
    return url_for('download_note_file',key=key)

def download_note_file(key):
    if not any(session.get(k) for k in ('student_logged_in','teacher_logged_in','admin_logged_in')):abort(403)
    if not re.fullmatch(r'notes/[0-9a-f]{32}/[A-Za-z0-9_.-]+',key):abort(404)
    bucket=os.environ.get('S3_BUCKET')
    if bucket:
        import boto3
        return redirect(boto3.client('s3',region_name=os.environ.get('AWS_REGION','eu-north-1'),endpoint_url='https://s3.'+os.environ.get('AWS_REGION','eu-north-1')+'.amazonaws.com').generate_presigned_url('get_object',Params={'Bucket':bucket,'Key':key},ExpiresIn=300))
    return send_from_directory(Path(current_app.root_path)/'.local'/'uploads',key,as_attachment=True)
