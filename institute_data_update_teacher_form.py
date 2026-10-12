from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import Optional

class InstituteUpdateTeacher(FlaskForm):
    regd_no = StringField("Search by Faculty ID", validators=[Optional()])
    name = StringField("Search by Name", validators=[Optional()])
    submit = SubmitField("Search")