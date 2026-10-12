from flask_wtf import FlaskForm
from wtforms import (
    SelectField,
    StringField,
    TextAreaField,
    IntegerField,
    SubmitField
)
from wtforms.validators import DataRequired, Length, URL, NumberRange, Optional
from flask_wtf.file import FileField, FileAllowed


class SubjectNotesForm(FlaskForm):

    year = SelectField(
        "Year",
        choices=[
            ("","Select Year"),
            ("1st Year", "1st Year"),
            ("2nd Year", "2nd Year"),
            ("3rd Year", "3rd Year"),
            ("4th Year", "4th Year")
        ],
        validators=[DataRequired()]
    )

    branch = SelectField(
        "Branch",
        choices=[
            ("","Select Branch"),
            ("CSE", "CSE"), ("ISE", "Information Science & Engineering"),
            ("ECE", "ECE"),
            ("MECH", "MECH"),
            ("CIVIL", "CIVIL"),
            ("EE", "EE")
        ],
        validators=[DataRequired()]
    )

    subject_name = StringField(
        "Subject Name",
        validators=[DataRequired(), Length(min=2, max=100)]
    )

    chapter_name = StringField(
        "Chapter Name",
        validators=[DataRequired(), Length(min=2, max=150)]
    )

    summary = TextAreaField(
        "Summary",
        validators=[DataRequired(), Length(min=5)]
    )

    notes_link = StringField(
        "Notes Link",
        validators=[Optional(), URL()]
    )

    notes_file = FileField('Upload notes (PDF, TXT, DOCX)', validators=[FileAllowed(['pdf', 'txt', 'docx'])])

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators)
        if not self.notes_link.data and not self.notes_file.data:
            self.notes_link.errors.append('Provide a notes link or upload a file.')
            return False
        return valid

    submit = SubmitField("Add Subject Notes")