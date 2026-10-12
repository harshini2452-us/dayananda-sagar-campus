"""Fee records and notification automation for the existing campus portal."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from flask import Blueprint, abort, current_app, flash, redirect, render_template, session, url_for
from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, DateField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange
import MySQLdb.cursors

portal = Blueprint('campus', __name__)
mysql = None

class ChargeForm(FlaskForm):
    usn = StringField('Student USN', validators=[DataRequired(), Length(max=50)])
    description = StringField('Fee description', validators=[DataRequired(), Length(max=150)])
    amount = DecimalField('Amount (INR)', places=2, validators=[DataRequired(), NumberRange(min=Decimal('1'), max=Decimal('1000000'))])
    due_date = DateField('Due date', validators=[DataRequired()])
    submit = SubmitField('Create fee record')

class PaymentForm(FlaskForm):
    amount = DecimalField('Payment amount (INR)', places=2, validators=[DataRequired(), NumberRange(min=Decimal('0.01'), max=Decimal('1000000'))])
    reference = StringField('Receipt / transaction reference', validators=[DataRequired(), Length(min=3, max=100)])
    submit = SubmitField('Record payment')

class ActionForm(FlaskForm):
    submit = SubmitField('Run reminders now')

def today():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()

def cursor():
    return mysql.connection.cursor(MySQLdb.cursors.DictCursor)

def student_only():
    if not session.get('student_logged_in'):abort(403)
    return session['student_regd']

def admin_only():
    if not session.get('admin_logged_in'):abort(403)

def decorate_fee(fee):
    fee['balance'] = fee['amount'] - fee['paid_amount']
    fee['status'] = ('Paid' if fee['balance'] == 0 else 'Overdue' if fee['due_date'] < today() else 'Partially paid' if fee['paid_amount'] else 'Pending')
    return fee

def notify(cur, usn, kind, title, message, key):
    cur.execute('''INSERT INTO notifications
        (regd_no,kind,title,message,dedup_key) VALUES (%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE title=VALUES(title),message=VALUES(message)''',
        (usn,kind,title,message,key))
    return int(cur.rowcount == 1)

def generate_notifications():
    """Repeat-safe daily checks. Financial details stay inside each student's inbox."""
    cur=cursor(); created=0; day=today(); day_key=day.isoformat()
    cur.execute('''SELECT f.* FROM fees f JOIN students s ON s.regd_no=f.regd_no
        WHERE f.amount>f.paid_amount AND f.due_date<=%s''',(day+timedelta(days=7),))
    for fee in cur.fetchall():
        balance=fee['amount']-fee['paid_amount']; overdue=fee['due_date']<day
        created+=notify(cur,fee['regd_no'],'fees','Fee payment overdue' if overdue else 'Upcoming fee payment',
            f"{fee['description']}: INR {balance:,.2f} outstanding. Due date: {fee['due_date']:%d %b %Y}. Review your fee statement or contact the accounts office.",
            f"fee:{fee['fee_id']}:{day_key}")
    cur.execute('''SELECT a.regd_no,a.subject_id,su.subject_name,
        COUNT(*) AS total, SUM(a.status='Present') AS present
        FROM attendance a JOIN subjects su ON su.subject_id=a.subject_id
        JOIN students st ON st.regd_no=a.regd_no
        GROUP BY a.regd_no,a.subject_id,su.subject_name HAVING COUNT(*)>0''')
    threshold=int(current_app.config.get('ATTENDANCE_ALERT_THRESHOLD',75))
    for row in cur.fetchall():
        percent=round(100*row['present']/row['total'],2)
        if percent<threshold:
            created+=notify(cur,row['regd_no'],'attendance','Attendance below requirement',
                f"Your attendance in {row['subject_name']} is {percent:.2f}% ({row['present']}/{row['total']} classes). The attendance requirement is {threshold}%. Please contact your course faculty.",
                f"attendance:{row['regd_no']}:{row['subject_id']}:{day_key}")
    cur.execute('SELECT regd_no,branch FROM students'); students=cur.fetchall()
    cur.execute('SELECT id,title,description,department FROM notices WHERE is_active=1'); notices=cur.fetchall()
    for notice in notices:
        for student in students:
            if notice['department'] in (student['branch'],'All','ALL','General','') or not notice['department']:
                created+=notify(cur,student['regd_no'],'notice',notice['title'],notice['description'],
                    f"notice:{notice['id']}:{student['regd_no']}")
    mysql.connection.commit();cur.close()
    current_app.logger.info('Notification automation completed: %s new inbox messages',created)
    return created

def publish_digest():
    """Optional SNS digest, using the instance/Lambda IAM role; no embedded AWS keys."""
    topic=os.environ.get('SNS_TOPIC_ARN')
    if not topic:return {'status':'not_configured','count':0}
    cur=cursor()
    # A database advisory lock prevents concurrent workers publishing the same batch.
    cur.execute("SELECT GET_LOCK('dsce_notification_delivery',0) AS acquired")
    if cur.fetchone()['acquired']!=1:cur.close();return {'status':'busy','count':0}
    try:
        cur.execute("SELECT notification_id FROM notifications WHERE cloud_status IN ('Pending','Failed') ORDER BY notification_id LIMIT 1000")
        ids=[r['notification_id'] for r in cur.fetchall()]
        if not ids:return {'status':'up_to_date','count':0}
        import boto3
        from botocore.config import Config
        client=boto3.client('sns',region_name=os.environ.get('AWS_REGION','ap-south-1'),
            config=Config(connect_timeout=5,read_timeout=10,retries={'max_attempts':2}))
        result=client.publish(TopicArn=topic,Subject='DSCE Campus Portal Updates',
            Message='New fee, attendance or announcement updates are available in the DSCE campus portal. Sign in to your own account to view the details. '+os.environ.get('PORTAL_PUBLIC_URL',''))
        placeholders=','.join(['%s']*len(ids))
        cur.execute(f"UPDATE notifications SET cloud_status='Sent',cloud_message_id=%s WHERE notification_id IN ({placeholders})",(result['MessageId'],*ids))
        mysql.connection.commit()
        current_app.logger.info('SNS digest published for %s inbox messages',len(ids))
        return {'status':'sent','count':len(ids)}
    except Exception:
        mysql.connection.rollback()
        current_app.logger.exception('SNS notification delivery failed')
        return {'status':'failed','count':0}
    finally:
        cur.execute("SELECT RELEASE_LOCK('dsce_notification_delivery')");cur.close()

@portal.route('/student/fees')
def student_fees():
    usn=student_only();cur=cursor()
    cur.execute('SELECT * FROM fees WHERE regd_no=%s ORDER BY due_date,fee_id',(usn,))
    fees=[decorate_fee(r) for r in cur.fetchall()]
    cur.execute('''SELECT p.*,f.description FROM fee_payments p JOIN fees f ON f.fee_id=p.fee_id
        WHERE f.regd_no=%s ORDER BY p.created_at DESC''',(usn,));payments=cur.fetchall();cur.close()
    return render_template('student_fees.html',fees=fees,payments=payments,
        total=sum(f['amount'] for f in fees),paid=sum(f['paid_amount'] for f in fees),
        balance=sum(f['balance'] for f in fees))

@portal.route('/student/notifications')
def student_notifications():
    usn=student_only();cur=cursor()
    cur.execute('SELECT * FROM notifications WHERE regd_no=%s ORDER BY created_at DESC,notification_id DESC',(usn,))
    messages=cur.fetchall();cur.close()
    return render_template('student_notifications.html',messages=messages,form=ActionForm())

@portal.route('/student/notifications/<int:notification_id>/read',methods=['POST'])
def read_notification(notification_id):
    usn=student_only();form=ActionForm()
    if not form.validate_on_submit():abort(400)
    cur=cursor();cur.execute('UPDATE notifications SET is_read=1 WHERE notification_id=%s AND regd_no=%s',(notification_id,usn))
    mysql.connection.commit();cur.close()
    return redirect(url_for('campus.student_notifications'))

@portal.route('/admin/fees',methods=['GET','POST'])
def admin_fees():
    admin_only();form=ChargeForm();cur=cursor()
    if form.validate_on_submit():
        usn=form.usn.data.strip().upper()
        cur.execute('SELECT regd_no FROM students WHERE regd_no=%s',(usn,))
        if not cur.fetchone():form.usn.errors.append('No student exists with this USN.')
        else:
            cur.execute('INSERT INTO fees(regd_no,description,amount,due_date) VALUES (%s,%s,%s,%s)',
                (usn,form.description.data.strip(),form.amount.data,form.due_date.data))
            mysql.connection.commit();cur.close();generate_notifications()
            flash('Fee record created.','success');return redirect(url_for('campus.admin_fees'))
    cur.execute('''SELECT f.*,s.name FROM fees f JOIN students s ON s.regd_no=f.regd_no
        ORDER BY f.due_date,f.regd_no''')
    fees=[decorate_fee(r) for r in cur.fetchall()];cur.close()
    return render_template('admin_fees.html',fees=fees,form=form)

@portal.route('/admin/fees/<int:fee_id>/payment',methods=['GET','POST'])
def record_payment(fee_id):
    admin_only();form=PaymentForm();cur=cursor()
    cur.execute('SELECT f.*,s.name FROM fees f JOIN students s ON s.regd_no=f.regd_no WHERE fee_id=%s',(fee_id,))
    fee=cur.fetchone()
    if not fee:cur.close();abort(404)
    fee=decorate_fee(fee)
    if form.validate_on_submit():
        cur.execute('SELECT amount,paid_amount FROM fees WHERE fee_id=%s FOR UPDATE',(fee_id,));locked=cur.fetchone()
        remaining=locked['amount']-locked['paid_amount']
        if form.amount.data>remaining:
            mysql.connection.rollback();form.amount.errors.append('Payment exceeds the outstanding balance.')
        else:
            try:
                cur.execute('INSERT INTO fee_payments(fee_id,amount,reference,recorded_by) VALUES (%s,%s,%s,%s)',
                    (fee_id,form.amount.data,form.reference.data.strip(),session['admin_regd']))
                cur.execute('UPDATE fees SET paid_amount=paid_amount+%s WHERE fee_id=%s',(form.amount.data,fee_id))
                notify(cur,fee['regd_no'],'receipt','Payment recorded',
                    f"INR {form.amount.data:,.2f} has been recorded against {fee['description']}. Receipt: {form.reference.data.strip()}.",
                    'receipt:'+form.reference.data.strip())
                balance=remaining-form.amount.data
                cur.execute('UPDATE notifications SET title=%s,message=%s WHERE dedup_key=%s',
                    ('Fee balance updated' if balance else 'Fee payment completed',
                     f"{fee['description']}: INR {balance:,.2f} outstanding after your latest payment. Due date: {fee['due_date']:%d %b %Y}.",
                     f"fee:{fee_id}:{today().isoformat()}"))
                mysql.connection.commit();cur.close()
                flash('Payment recorded and student notified.','success');return redirect(url_for('campus.admin_fees'))
            except MySQLdb.IntegrityError:
                mysql.connection.rollback();form.reference.errors.append('This receipt reference is already recorded.')
    cur.close();return render_template('fee_payment.html',fee=fee,form=form)

@portal.route('/admin/notifications',methods=['GET','POST'])
def admin_notifications():
    admin_only();form=ActionForm()
    if form.validate_on_submit():
        count=generate_notifications();delivery=publish_digest()
        flash(f"Reminder check complete: {count} new notifications. Existing reminders were kept without duplicates.",'success')
        if delivery['status']=='failed':flash('Inbox notifications are available; cloud delivery needs attention.','warning')
        return redirect(url_for('campus.admin_notifications'))
    cur=cursor();cur.execute('''SELECT n.*,s.name FROM notifications n JOIN students s ON s.regd_no=n.regd_no
        ORDER BY n.notification_id DESC LIMIT 100''');messages=cur.fetchall();cur.close()
    return render_template('admin_notifications.html',messages=messages,form=form,
        cloud_connected=bool(os.environ.get('SNS_TOPIC_ARN')))

def init_services(app,database):
    global mysql
    mysql=database;app.register_blueprint(portal)
    @app.cli.command('run-notifications')
    def run_notifications():
        import click
        count=generate_notifications();result=publish_digest()
        click.echo(f"Created {count} notifications; cloud delivery: {result['status']}.")
        if result['status']=='failed':raise click.ClickException('SNS delivery failed; inbox updates are retained for retry.')
