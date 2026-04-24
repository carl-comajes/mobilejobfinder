from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from cloudinary_storage.storage import RawMediaCloudinaryStorage

# Custom User Manager
class CustomUserManager(BaseUserManager):
    def create_user(self, email, username, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        if not username:
            raise ValueError("Username is required")
        
        email = self.normalize_email(email)
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)  # Hashes the password
        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, username, password, **extra_fields)

# Custom User Model
class CustomUser(AbstractBaseUser, PermissionsMixin):
    groups = models.ManyToManyField(
        'auth.Group', related_name='customuser_set', blank=True
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission', related_name='customuser_set', blank=True
    )
    GENDER_CHOICES = [
        ("Male", "Male"),
        ("Female", "Female"),
        ("Other", "Other"),
    ]

    first_name = models.CharField(max_length=50)
    middle_name = models.CharField(max_length=50, blank=True, null=True)  # Optional
    last_name = models.CharField(max_length=50)
    username = models.CharField(max_length=50, unique=True)
    contact = models.CharField(max_length=15, unique=True)
    address = models.TextField()
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)  # Stored as a hashed password

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_recruiter = models.BooleanField(default=False)
    company = models.CharField(max_length=150, blank=True, default='')
    company_description = models.TextField(blank=True, default='')
    industry = models.CharField(max_length=120, blank=True, default='')

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "first_name", "last_name", "contact", "address", "gender"]

    def __str__(self):
        return self.username


class Job(models.Model):
    JOB_TYPE_CHOICES = [
        ("Full-time", "Full-time"),
        ("Part-time", "Part-time"),
        ("Remote", "Remote"),
        ("Contract", "Contract"),
        ("Internship", "Internship"),
    ]
    CATEGORY_CHOICES = [
        ("IT", "IT"),
        ("Healthcare", "Healthcare"),
        ("Education", "Education"),
        ("Finance", "Finance"),
        ("Engineering", "Engineering"),
        ("Customer Service", "Customer Service"),
        ("Marketing", "Marketing"),
        ("General", "General"),
    ]

    title = models.CharField(max_length=150)
    company = models.CharField(max_length=150)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default="General")
    location = models.CharField(max_length=120)
    salary = models.CharField(max_length=100)
    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES)
    description = models.TextField()
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.company}"


class Country(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)  # e.g. PH, US
    flag = models.CharField(max_length=10, blank=True)   # emoji flag

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PasswordResetOTP(models.Model):
    user       = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='otps')
    code       = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used    = models.BooleanField(default=False)

    def is_expired(self):
        from django.utils import timezone
        from datetime import timedelta
        return timezone.now() > self.created_at + timedelta(minutes=10)

    def __str__(self):
        return f"{self.user.email} - {self.code}"


class UserProfile(models.Model):
    EXPERIENCE_CHOICES = [
        ("Entry Level", "Entry Level"),
        ("Mid Level", "Mid Level"),
        ("Senior Level", "Senior Level"),
        ("Executive", "Executive"),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="profile")
    job_title = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    skills = models.TextField(blank=True, help_text="Comma-separated skills")
    experience_summary = models.TextField(blank=True)
    experience_level = models.CharField(max_length=20, choices=EXPERIENCE_CHOICES, blank=True)
    portfolio_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    profile_picture = models.FileField(upload_to="profile_pictures/", blank=True, null=True)
    resume = models.FileField(upload_to="resumes/", storage=RawMediaCloudinaryStorage(), blank=True, null=True)
    is_complete = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} profile"


class Message(models.Model):
    sender    = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="sent_messages")
    recipient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="received_messages")
    body      = models.TextField()
    is_read   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender.username} → {self.recipient.username}"


class Notification(models.Model):
    recipient   = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="notifications")
    sender      = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_notifications")
    title       = models.CharField(max_length=200)
    message     = models.TextField()
    is_read     = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient.username} — {self.title}"


class Application(models.Model):
    STATUS_CHOICES = [
        ("Submitted", "Submitted"),
        ("Under Review", "Under Review"),
        ("Interview", "Interview"),
        ("Rejected", "Rejected"),
        ("Hired", "Hired"),
        ("Cancelled", "Cancelled"),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="applications")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="applications")
    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    address = models.TextField()
    cover_letter = models.TextField()
    experience = models.TextField()
    resume = models.FileField(upload_to="application_resumes/", storage=RawMediaCloudinaryStorage(), blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Submitted")
    cancel_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("user", "job")

    def __str__(self):
        return f"{self.full_name} -> {self.job.title}"
    
# class RegistrationForm(models.Model):
#     REGISTRATION_TYPES = [
#         ('Free', 'Free'),
#         ('Early Bird', 'Early Bird'),
#         ('Regular', 'Regular'),
#         ('Student', 'Student'),
#         ('VIP', 'VIP'),
#     ]

#     SEMINAR_TOPICS = [
#         ('tech', 'Technology Trends'),
#         ('business', 'Business Growth'),
#         ('career', 'Career Development'),
#         # Add more topics as needed
#     ]

#     # Personal Information
#     full_name = models.CharField(max_length=255)
#     email = models.EmailField()
#     phone_number = models.CharField(max_length=20)
#     organization = models.CharField(max_length=255, blank=True, null=True)
#     job_title = models.CharField(max_length=255, blank=True, null=True)

#     # Seminar Preferences
#     topics_of_interest = models.ManyToManyField("SeminarTopic", blank=True)
#     needs_accommodation = models.BooleanField(default=False)
#     accommodation_details = models.TextField(blank=True, null=True)

#     # Dietary Information
#     has_dietary_restrictions = models.BooleanField(default=False)
#     dietary_details = models.TextField(blank=True, null=True)

#     # Payment
#     registration_type = models.CharField(max_length=20, choices=REGISTRATION_TYPES)
#     total_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)

#     # Additional Information
#     heard_about = models.CharField(max_length=255, blank=True, null=True)
#     comments = models.TextField(blank=True, null=True)

#     # Terms & Conditions
#     agreed_to_terms = models.BooleanField(default=False)

#     submitted_at = models.DateTimeField(auto_now_add=True)

#     def __str__(self):
#         return f"{self.full_name} - {self.registration_type}"

# class SeminarTopic(models.Model):
#     name = models.CharField(max_length=100)

#     def __str__(self):
#         return self.name
