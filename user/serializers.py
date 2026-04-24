from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import Application, Country, CustomUser, Job, Message, Notification, UserProfile


class MessageSerializer(serializers.ModelSerializer):
    sender_name   = serializers.CharField(source="sender.username", read_only=True)
    recipient_name = serializers.CharField(source="recipient.username", read_only=True)

    class Meta:
        model = Message
        fields = ["id", "sender", "sender_name", "recipient", "recipient_name", "body", "is_read", "created_at"]
        read_only_fields = ["id", "sender", "sender_name", "recipient_name", "is_read", "created_at"]


class NotificationSerializer(serializers.ModelSerializer):
    sender_name  = serializers.CharField(source="sender.username", read_only=True, default=None)
    sender_email = serializers.EmailField(source="sender.email", read_only=True, default=None)

    class Meta:
        model = Notification
        fields = ["id", "title", "message", "is_read", "created_at", "sender_name", "sender_email"]
        read_only_fields = ["id", "created_at"]


class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            "id", "first_name", "last_name", "username",
            "email", "contact", "address", "gender",
            "company", "company_description", "industry",
            "is_staff", "is_active", "is_recruiter",
        ]
        read_only_fields = ["id"]


class RecruiterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = CustomUser
        fields = [
            "id", "first_name", "last_name", "username",
            "email", "contact", "company", "company_description", "industry", "is_active", "password",
        ]
        read_only_fields = ["id"]

    def validate_email(self, value):
        qs = CustomUser.objects.filter(email=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This email is already in use.")
        return value

    def validate_username(self, value):
        qs = CustomUser.objects.filter(username=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_contact(self, value):
        qs = CustomUser.objects.filter(contact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This contact number is already in use.")
        return value

    def validate(self, data):
        if not self.instance and not data.get("password", "").strip():
            raise serializers.ValidationError({"password": "Password is required when creating a recruiter."})
        if not self.instance:
            missing = {}
            for field in ("company", "company_description", "industry"):
                if not data.get(field, "").strip():
                    missing[field] = "This field is required for recruiter signup."
            if missing:
                raise serializers.ValidationError(missing)
        return data

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        validated_data["is_recruiter"] = True
        validated_data.setdefault("address", "N/A")
        validated_data.setdefault("gender", "Other")
        validated_data.setdefault("company", "")
        validated_data.setdefault("company_description", "")
        validated_data.setdefault("industry", "")
        user = CustomUser(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password and password.strip():
            instance.set_password(password)
        instance.save()
        return instance


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True, required=True)
    role = serializers.CharField(write_only=True, required=False, default="job_seeker")

    class Meta:
        model = CustomUser
        fields = [
            "id", "first_name", "middle_name", "last_name", "username",
            "contact", "address", "gender", "email",
            "company", "company_description", "industry",
            "password", "confirm_password", "role",
        ]

    def validate(self, data):
        if CustomUser.objects.filter(username=data["username"]).exists():
            raise serializers.ValidationError({"username": "This username is already taken."})
        if CustomUser.objects.filter(email=data["email"]).exists():
            raise serializers.ValidationError({"email": "This email is already in use."})
        if data["password"] != data["confirm_password"]:
            raise serializers.ValidationError({"password": "Passwords do not match!"})
        if data.get("role", "job_seeker") == "recruiter":
            missing = {}
            for field in ("company", "company_description", "industry"):
                if not data.get(field, "").strip():
                    missing[field] = "This field is required for recruiter signup."
            if missing:
                raise serializers.ValidationError(missing)
        return data

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        role = validated_data.pop("role", "job_seeker")
        validated_data.setdefault("company", "")
        validated_data.setdefault("company_description", "")
        validated_data.setdefault("industry", "")
        user = CustomUser.objects.create_user(**validated_data)
        if role == "recruiter":
            user.is_recruiter = True
            user.save()
        return user


class JobSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)

    class Meta:
        model = Job
        fields = [
            "id", "title", "company", "category", "location", "salary",
            "job_type", "description", "created_by", "created_by_email",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_by_email", "created_at", "updated_at"]


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            "id", "first_name", "middle_name", "last_name", "username",
            "contact", "address", "gender", "email",
        ]
        read_only_fields = ["id", "email"]


class UserProfileSerializer(serializers.ModelSerializer):
    profile_picture_url = serializers.SerializerMethodField()
    resume_url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            "id", "job_title", "bio", "skills",
            "experience_summary", "experience_level", "portfolio_url", "linkedin_url",
            "profile_picture", "profile_picture_url", "resume", "resume_url",
            "is_complete", "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]

    def get_profile_picture_url(self, obj):
        request = self.context.get("request")
        if not obj.profile_picture:
            return ""
        if request:
            return request.build_absolute_uri(obj.profile_picture.url)
        return obj.profile_picture.url

    def get_resume_url(self, obj):
        request = self.context.get("request")
        if not obj.resume:
            return ""
        if request:
            return request.build_absolute_uri(obj.resume.url)
        return obj.resume.url


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ["id", "name", "code", "flag"]


class ApplicationSerializer(serializers.ModelSerializer):
    job_title = serializers.CharField(source="job.title", read_only=True)
    company = serializers.CharField(source="job.company", read_only=True)
    location = serializers.CharField(source="job.location", read_only=True)
    salary = serializers.CharField(source="job.salary", read_only=True)
    job_type = serializers.CharField(source="job.job_type", read_only=True)
    resume_url = serializers.SerializerMethodField()
    full_name = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    cover_letter = serializers.CharField(required=True, allow_blank=False)
    experience = serializers.CharField(required=True, allow_blank=False)

    class Meta:
        model = Application
        fields = [
            "id", "user", "job", "job_title", "company", "location",
            "salary", "job_type", "full_name", "email", "phone", "address",
            "cover_letter", "experience", "resume", "resume_url", "status", "cancel_reason", "created_at", "updated_at",
        ]
        read_only_fields = ["user", "created_at", "updated_at"]

    def validate(self, data):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        job = data.get("job")
        if not str(data.get("cover_letter", "")).strip():
            raise serializers.ValidationError({"cover_letter": "This field is required."})
        if not str(data.get("experience", "")).strip():
            raise serializers.ValidationError({"experience": "This field is required."})

        if request and request.method == "POST" and user and job:
            if Application.objects.filter(user=user, job=job).exists():
                raise serializers.ValidationError({"job": "You have already applied to this job."})
        return data

    def get_resume_url(self, obj):
        request = self.context.get("request")
        if not obj.resume:
            return ""
        if request:
            return request.build_absolute_uri(obj.resume.url)
        return obj.resume.url
