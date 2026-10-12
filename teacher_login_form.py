from flask_wtf import FlaskForm
from wtforms import StringField , PasswordField , EmailField , SubmitField
from wtforms.validators import DataRequired , Email , ValidationError

class TeacherLoginForm(FlaskForm):
    regd = StringField("Faculty ID" , validators=[DataRequired()])
    password = PasswordField("Password" , validators=[DataRequired()])
    submit = SubmitField("Login")