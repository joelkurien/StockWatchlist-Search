from django.db import models
from django.core.exceptions import ValidationError
import re
import random
import string

# Create your models here.
class UserLogin(models.Model):
    userID = models.CharField(max_length=8, unique=True, editable=False)
    userName = models.CharField(max_length=255)
    userPassword = models.CharField(max_length=255)
    dateOfBirth = models.DateField()
    
    def clean(self):
        super().clean()
        if self.userName and self.userPassword and self.userName in self.userPassword:
            raise ValidationError({
                'userPassword': "Password cannot contain the username"
            })

        password_pattrn = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{8,}$"
        if not re.match(password_pattrn, self.userPassword):
            raise ValidationError({
                'userPassword': """Password must be 8 characters long with atleast 
                            one uppercase, lowercase character, one digit and 
                            one special character"""
            })
    
    @classmethod
    def generate_user_id(cls):
        while True:
            user_id = "".join(random.choices(string.ascii_letters + string.digits, k = 8))
            if not UserLogin.objects.filter(userID=user_id).exists():
                return user_id
    
    def save(self, *args, **kwargs):
        print('yes')
        if not self.userID:
            self.userID = self.generate_user_id()
        self.full_clean()
        super().save(*args, **kwargs)
        