import random
import re
from django.core.mail import send_mail
from django.db.models import Q
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Application, Country, CustomUser, Job, Message, Notification, PasswordResetOTP, SignupVerification, UserProfile
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import (
    AdminUserSerializer, ApplicationSerializer, CountrySerializer,
    JobSerializer, MessageSerializer, NotificationSerializer, ProfileSerializer,
    RecruiterSerializer, UserProfileSerializer, UserSerializer,
)


def _notify(recipient, title, message, sender=None):
    """Create a notification for a single user."""
    Notification.objects.create(recipient=recipient, title=title, message=message, sender=sender)


def _notify_all_staff(title, message, sender=None):
    """Send a notification to every staff (admin) user."""
    for admin in CustomUser.objects.filter(is_staff=True):
        _notify(admin, title, message, sender=sender)


def _generate_otp_code():
    return f"{random.randint(100000, 999999)}"


def _create_otp(user, purpose):
    PasswordResetOTP.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)
    return PasswordResetOTP.objects.create(user=user, purpose=purpose, code=_generate_otp_code())


def _create_signup_verification(payload):
    email = payload["email"].strip().lower()
    SignupVerification.objects.filter(email=email, is_used=False).delete()
    return SignupVerification.objects.create(
        email=email,
        payload=payload,
        code=_generate_otp_code(),
    )


def _send_otp_email(recipient_email, subject, body_lines):
    send_mail(
        subject=subject,
        message="\n".join(body_lines),
        from_email=None,
        recipient_list=[recipient_email],
        fail_silently=False,
    )


class CountryListView(generics.ListAPIView):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
    permission_classes = [permissions.AllowAny]


class ProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = ProfileSerializer(request.user)
        return Response(serializer.data)

    def put(self, request):
        serializer = ProfileSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return Response(UserProfileSerializer(profile, context={"request": request}).data)

    def put(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileSerializer(profile, data=request.data, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserRegisterView(APIView):
    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            payload = dict(serializer.validated_data)
            payload.pop("confirm_password", None)
            verification = _create_signup_verification(payload)
            try:
                _send_otp_email(
                    verification.email,
                    "PHINAS JOBS - Email Verification Code",
                    [
                        f"Hi {payload.get('first_name') or payload.get('username') or verification.email},",
                        "",
                        f"Your signup verification code is: {verification.code}",
                        "",
                        "This code expires in 10 minutes.",
                        "",
                        "If you did not create this account, you can ignore this email.",
                    ],
                )
            except Exception as exc:
                verification.delete()
                return Response(
                    {"error": f"Could not send the signup verification email: {exc}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            return Response(
                {
                    "message": "Verification code sent. Enter the code to complete signup.",
                    "email": verification.email,
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifySignupView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        code = request.data.get("code", "").strip()

        try:
            pending = SignupVerification.objects.get(email=email, is_used=False)
        except SignupVerification.DoesNotExist:
            return Response({"error": "No pending signup found for that email."}, status=status.HTTP_400_BAD_REQUEST)

        if pending.code != code:
            return Response({"error": "Invalid verification code."}, status=status.HTTP_400_BAD_REQUEST)
        if pending.is_expired():
            return Response({"error": "Verification code has expired. Please request a new one."}, status=status.HTTP_400_BAD_REQUEST)

        payload = dict(pending.payload)
        payload.pop("confirm_password", None)
        role = payload.pop("role", "job_seeker")
        payload.setdefault("company", "")
        payload.setdefault("company_description", "")
        payload.setdefault("industry", "")
        payload["is_email_verified"] = True

        if CustomUser.objects.filter(email=email).exists():
            return Response({"error": "This email is already in use."}, status=status.HTTP_400_BAD_REQUEST)
        if CustomUser.objects.filter(username=payload.get("username")).exists():
            return Response({"error": "This username is already taken."}, status=status.HTTP_400_BAD_REQUEST)
        if CustomUser.objects.filter(contact=payload.get("contact")).exists():
            return Response({"error": "This contact number is already in use."}, status=status.HTTP_400_BAD_REQUEST)

        user = CustomUser.objects.create_user(**payload)
        if role == "recruiter":
            user.is_recruiter = True
            user.save(update_fields=["is_recruiter"])

        pending.is_used = True
        pending.save(update_fields=["is_used"])
        pending.delete()

        return Response(
            {
                "message": "Signup verified successfully.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "is_recruiter": user.is_recruiter,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class ResendSignupVerificationView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        try:
            pending = SignupVerification.objects.get(email=email, is_used=False)
        except SignupVerification.DoesNotExist:
            return Response({"error": "No pending signup found for that email."}, status=status.HTTP_400_BAD_REQUEST)

        pending.code = _generate_otp_code()
        pending.save(update_fields=["code"])
        try:
            _send_otp_email(
                pending.email,
                "PHINAS JOBS - Email Verification Code",
                [
                    f"Hi {pending.payload.get('first_name') or pending.payload.get('username') or pending.email},",
                    "",
                    f"Your signup verification code is: {pending.code}",
                    "",
                    "This code expires in 10 minutes.",
                    "",
                    "If you did not create this account, you can ignore this email.",
                ],
            )
        except Exception:
            return Response(
                {"error": "We could not resend the verification code. Please check email settings."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({"message": "Verification code resent to your email."}, status=status.HTTP_200_OK)


class UserLoginView(APIView):
    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        user = authenticate(email=email, password=password)
        if user:
            if not user.is_email_verified:
                return Response(
                    {
                        'error': 'Please verify your email before logging in.',
                        'requires_verification': True,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            refresh = RefreshToken.for_user(user)
            profile, _ = UserProfile.objects.get_or_create(user=user)
            return Response({
                'access_token': str(refresh.access_token),
                'refresh_token': str(refresh),
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'company': user.company,
                    'company_description': user.company_description,
                    'industry': user.industry,
                    'is_staff': user.is_staff,
                    'is_recruiter': user.is_recruiter,
                    'profile_complete': profile.is_complete,
                },
            }, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)


class JobListCreateView(generics.ListCreateAPIView):
    queryset = Job.objects.all()
    serializer_class = JobSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    def get_queryset(self):
        queryset = Job.objects.all()
        params = self.request.query_params

        keyword = (params.get("keyword") or "").strip()
        location = (params.get("location") or "").strip()
        job_type = (params.get("job_type") or "").strip()
        category = (params.get("category") or "").strip()
        salary_min = self._parse_salary_bound(params.get("salary_min"))
        salary_max = self._parse_salary_bound(params.get("salary_max"))

        if keyword:
            queryset = queryset.filter(
                Q(title__icontains=keyword)
                | Q(company__icontains=keyword)
                | Q(description__icontains=keyword)
                | Q(category__icontains=keyword)
            )
        if location:
            queryset = queryset.filter(location__icontains=location)
        if job_type:
            queryset = queryset.filter(job_type__iexact=job_type)
        if category:
            queryset = queryset.filter(category__iexact=category)

        jobs = list(queryset)
        if salary_min is not None or salary_max is not None:
            jobs = [j for j in jobs if self._salary_matches(j.salary, salary_min, salary_max)]
        return jobs

    @staticmethod
    def _parse_salary_bound(raw_value):
        if raw_value in (None, ""):
            return None
        try:
            return int(float(str(raw_value).replace(",", "").strip()))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _salary_matches(salary_text, salary_min, salary_max):
        numbers = [int(m.replace(",", "")) for m in re.findall(r"\d[\d,]*", salary_text or "")]
        if not numbers:
            return True
        job_min = min(numbers)
        job_max = max(numbers)
        if salary_min is not None and job_max < salary_min:
            return False
        if salary_max is not None and job_min > salary_max:
            return False
        return True

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class JobDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated]


class AdminJobListCreateView(generics.ListCreateAPIView):
    queryset = Job.objects.select_related("created_by").all()
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAdminUser]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AdminJobDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Job.objects.select_related("created_by").all()
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAdminUser]


class ApplicationListCreateView(generics.ListCreateAPIView):
    serializer_class = ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        queryset = Application.objects.filter(user=self.request.user)
        job_id = self.request.query_params.get("job")
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        return queryset

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "request": self.request}

    def perform_create(self, serializer):
        applicant = self.request.user
        full_name = " ".join(
            part for part in [
                getattr(applicant, "first_name", "") or "",
                getattr(applicant, "last_name", "") or "",
            ]
            if part
        ).strip() or applicant.username or applicant.email

        application = serializer.save(
            user=applicant,
            full_name=full_name,
            email=applicant.email,
            phone=getattr(applicant, "contact", "") or "",
            address=getattr(applicant, "address", "") or "",
        )
        job = application.job

        # Notify the job's recruiter/creator
        if job.created_by:
            _notify(
                job.created_by,
                "New Application Received",
                f"{applicant.first_name or applicant.username} applied for '{job.title}' at {job.company}.",
                sender=applicant,
            )

        # Notify all admins
        _notify_all_staff(
            "New Job Application",
            f"{applicant.first_name or applicant.username} applied for '{job.title}' at {job.company}.",
            sender=applicant,
        )


class ApplicationDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_recruiter or user.is_staff:
            return Application.objects.filter(job__created_by=user)
        return Application.objects.filter(user=user)

    def perform_update(self, serializer):
        old_status = self.get_object().status
        application = serializer.save()
        new_status = application.status
        if new_status != old_status:
            _notify(
                application.user,
                "Application Status Updated",
                f"Your application for '{application.job.title}' at {application.job.company} is now: {new_status}.",
            )


class CancelApplicationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            application = Application.objects.get(pk=pk, user=request.user)
        except Application.DoesNotExist:
            return Response({"error": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        if application.status == "Cancelled":
            return Response({"error": "Already cancelled."}, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get("reason", "").strip()
        if not reason:
            return Response({"error": "A cancellation reason is required."}, status=status.HTTP_400_BAD_REQUEST)

        application.status = "Cancelled"
        application.cancel_reason = reason
        application.save()

        applicant = request.user
        job = application.job
        title = "Application Cancelled"
        message = (
            f"{applicant.first_name or applicant.username} cancelled their application "
            f"for '{job.title}' at {job.company}.\n\nReason: {reason}"
        )

        # Notify recruiter
        if job.created_by:
            _notify(job.created_by, title, message, sender=applicant)

        # Notify all admins
        _notify_all_staff(title, message, sender=applicant)

        return Response(ApplicationSerializer(application).data)


class AdminApplicationListView(generics.ListAPIView):
    serializer_class = ApplicationSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        queryset = Application.objects.select_related("user", "job").all()
        job_id = self.request.query_params.get("job")
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        return queryset

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "request": self.request}


class AdminApplicationStatusView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def patch(self, request, pk):
        try:
            application = Application.objects.select_related("job", "user").get(pk=pk)
        except Application.DoesNotExist:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        new_status = request.data.get("status")
        valid = [s[0] for s in Application.STATUS_CHOICES]
        if new_status not in valid:
            return Response({"error": f"Invalid status. Choose from {valid}"}, status=status.HTTP_400_BAD_REQUEST)
        application.status = new_status
        application.save()

        _notify(
            application.user,
            "Application Status Updated",
            f"Your application for '{application.job.title}' at {application.job.company} is now: {new_status}.",
        )

        return Response(ApplicationSerializer(application, context={"request": request}).data)


class RecruiterApplicationStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        user = request.user
        if not (user.is_recruiter or user.is_staff):
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        try:
            if user.is_staff:
                application = Application.objects.select_related("job", "user").get(pk=pk)
            else:
                application = Application.objects.select_related("job", "user").get(pk=pk, job__created_by=user)
        except Application.DoesNotExist:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get("status")
        valid = [s[0] for s in Application.STATUS_CHOICES]
        if new_status not in valid:
            return Response({"error": f"Invalid status. Choose from {valid}"}, status=status.HTTP_400_BAD_REQUEST)

        old_status = application.status
        application.status = new_status
        application.save()

        if new_status != old_status:
            _notify(
                application.user,
                "Application Status Updated",
                f"Your application for '{application.job.title}' at {application.job.company} is now: {new_status}.",
                sender=user,
            )

        return Response(ApplicationSerializer(application, context={"request": request}).data)


class NotificationReplyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk)
        except Notification.DoesNotExist:
            return Response({"error": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)

        if not (request.user.is_staff or request.user.is_recruiter):
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        message_text = request.data.get("message", "").strip()
        if not message_text:
            return Response({"error": "Message is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Reply goes to the original sender of the notification (the user who cancelled)
        reply_recipient = notification.sender if notification.sender else notification.recipient
        _notify(
            reply_recipient,
            f"Reply from {request.user.first_name or request.user.username}",
            message_text,
            sender=request.user,
        )
        return Response({"detail": "Reply sent."})


class AdminUserListView(generics.ListCreateAPIView):
    queryset = CustomUser.objects.all().order_by('-id')
    serializer_class = AdminUserSerializer
    permission_classes = [permissions.IsAdminUser]


class AdminUserDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = CustomUser.objects.all()
    serializer_class = AdminUserSerializer
    permission_classes = [permissions.IsAdminUser]


class AdminStatsView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        return Response({
            "total_users": CustomUser.objects.count(),
            "total_jobs": Job.objects.count(),
            "total_applications": Application.objects.count(),
            "hired": Application.objects.filter(status="Hired").count(),
            "under_review": Application.objects.filter(status="Under Review").count(),
            "interview": Application.objects.filter(status="Interview").count(),
            "rejected": Application.objects.filter(status="Rejected").count(),
            "submitted": Application.objects.filter(status="Submitted").count(),
            "cancelled": Application.objects.filter(status="Cancelled").count(),
        })


class RecruiterJobListView(generics.ListAPIView):
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Job.objects.filter(created_by=self.request.user).order_by('-created_at')


class RecruiterApplicationListView(generics.ListAPIView):
    serializer_class = ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Application.objects.filter(
            job__created_by=self.request.user
        ).select_related('job').order_by('-created_at')

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "request": self.request}


class AdminRecruiterListCreateView(generics.ListCreateAPIView):
    serializer_class = RecruiterSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return CustomUser.objects.filter(is_recruiter=True).order_by('-id')


class AdminRecruiterDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = RecruiterSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return CustomUser.objects.filter(is_recruiter=True)


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)


class NotificationMarkReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return Response({"detail": "All notifications marked as read."})


class MessageInboxView(generics.ListAPIView):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Message.objects.filter(recipient=self.request.user).order_by("-created_at")


class MessageSendView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        recipient_id = request.data.get("recipient")
        body = request.data.get("body", "").strip()
        if not body:
            return Response({"error": "Message body is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            recipient = CustomUser.objects.get(pk=recipient_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "Recipient not found."}, status=status.HTTP_404_NOT_FOUND)
        msg = Message.objects.create(sender=request.user, recipient=recipient, body=body)
        _notify(recipient, f"New message from {request.user.username}", body[:120])
        return Response(MessageSerializer(msg).data, status=status.HTTP_201_CREATED)


class MessageThreadView(generics.ListAPIView):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        other_id = self.kwargs["user_id"]
        me = self.request.user
        return Message.objects.filter(
            Q(sender=me, recipient_id=other_id) | Q(sender_id=other_id, recipient=me)
        ).order_by("created_at")


class AdminRecruiterListView(generics.ListAPIView):
    """Returns all admins and recruiters so the user can pick a message recipient."""
    serializer_class = AdminUserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return CustomUser.objects.filter(
            Q(is_staff=True) | Q(is_recruiter=True)
        ).exclude(pk=self.request.user.pk).order_by("username")


class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response({'error': 'No account found with that email.'}, status=status.HTTP_404_NOT_FOUND)

        otp = _create_otp(user, PasswordResetOTP.PURPOSE_PASSWORD_RESET)
        try:
            _send_otp_email(
                user,
                "PHINAS JOBS - Password Reset Code",
                [
                    f"Hi {user.first_name or user.username},",
                    "",
                    f"Your password reset code is: {otp.code}",
                    "",
                    "This code expires in 10 minutes.",
                    "",
                    "If you did not request this, ignore this email.",
                ],
            )
        except Exception:
            otp.delete()
            return Response(
                {'error': 'We could not send the reset code. Please check email settings.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({'message': 'OTP sent to your email.'}, status=status.HTTP_200_OK)


class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        code = request.data.get('code', '').strip()

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response({'error': 'Invalid request.'}, status=status.HTTP_400_BAD_REQUEST)

        if user.is_email_verified:
            return Response({'message': 'Email is already verified.'}, status=status.HTTP_200_OK)

        otp = PasswordResetOTP.objects.filter(
            user=user,
            purpose=PasswordResetOTP.PURPOSE_EMAIL_VERIFICATION,
            code=code,
            is_used=False,
        ).order_by('-created_at').first()
        if not otp:
            return Response({'error': 'Invalid or already used verification code.'}, status=status.HTTP_400_BAD_REQUEST)
        if otp.is_expired():
            return Response({'error': 'Verification code has expired. Please request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

        user.is_email_verified = True
        user.save(update_fields=['is_email_verified'])
        otp.is_used = True
        otp.save(update_fields=['is_used'])
        return Response({'message': 'Email verified successfully.'}, status=status.HTTP_200_OK)


class ResendEmailVerificationView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response({'error': 'Invalid request.'}, status=status.HTTP_400_BAD_REQUEST)

        if user.is_email_verified:
            return Response({'message': 'Email is already verified.'}, status=status.HTTP_200_OK)

        otp = _create_otp(user, PasswordResetOTP.PURPOSE_EMAIL_VERIFICATION)
        try:
            _send_otp_email(
                user,
                "PHINAS JOBS - Email Verification Code",
                [
                    f"Hi {user.first_name or user.username},",
                    "",
                    f"Your email verification code is: {otp.code}",
                    "",
                    "This code expires in 10 minutes.",
                    "",
                    "If you did not create this account, you can ignore this email.",
                ],
            )
        except Exception:
            otp.delete()
            return Response(
                {'error': 'We could not resend the verification code. Please check email settings.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({'message': 'Verification code resent to your email.'}, status=status.HTTP_200_OK)


class VerifyResetOtpView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        code = request.data.get('code', '').strip()

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response({'error': 'Invalid request.'}, status=status.HTTP_400_BAD_REQUEST)

        otp = PasswordResetOTP.objects.filter(
            user=user,
            purpose=PasswordResetOTP.PURPOSE_PASSWORD_RESET,
            code=code,
            is_used=False,
        ).order_by('-created_at').first()
        if not otp:
            return Response({'error': 'Invalid or already used OTP.'}, status=status.HTTP_400_BAD_REQUEST)
        if otp.is_expired():
            return Response({'error': 'OTP has expired. Please request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'message': 'OTP verified successfully.'}, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email    = request.data.get('email', '').strip()
        code     = request.data.get('code', '').strip()
        password = request.data.get('password', '')

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response({'error': 'Invalid request.'}, status=status.HTTP_400_BAD_REQUEST)

        otp = PasswordResetOTP.objects.filter(
            user=user,
            purpose=PasswordResetOTP.PURPOSE_PASSWORD_RESET,
            code=code,
            is_used=False,
        ).order_by('-created_at').first()
        if not otp:
            return Response({'error': 'Invalid or already used OTP.'}, status=status.HTTP_400_BAD_REQUEST)
        if otp.is_expired():
            return Response({'error': 'OTP has expired. Please request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(password)
        user.save()
        otp.is_used = True
        otp.save()
        return Response({'message': 'Password reset successful.'}, status=status.HTTP_200_OK)
