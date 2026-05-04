from unittest.mock import patch

from django.urls import reverse
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import CustomUser, PasswordResetOTP, SignupVerification


@override_settings(ALLOWED_HOSTS=["testserver"])
class PasswordResetFlowTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="john.doe@example.com",
            username="johndoe",
            password="StrongPass123!",
            first_name="John",
            last_name="Doe",
            contact="09171234567",
            address="Test Address",
            gender="Male",
        )

    @patch("user.views.send_mail")
    def test_forgot_password_uses_case_insensitive_email_lookup_and_sends_to_email_address(self, mock_send_mail):
        response = self.client.post(
            reverse("forgot-password"),
            {"email": "JOHN.DOE@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.user, purpose=PasswordResetOTP.PURPOSE_PASSWORD_RESET).count(), 1)
        mock_send_mail.assert_called_once()
        self.assertEqual(mock_send_mail.call_args.kwargs["recipient_list"], [self.user.email])


@override_settings(ALLOWED_HOSTS=["testserver"])
class SignupVerificationFlowTests(APITestCase):
    def test_register_rejects_duplicate_contact_before_sending_email(self):
        CustomUser.objects.create_user(
            email="existing@example.com",
            username="existinguser",
            password="StrongPass123!",
            first_name="Existing",
            last_name="User",
            contact="09170000009",
            address="Test Address",
            gender="Male",
        )

        response = self.client.post(
            reverse("user"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "username": "janedoe",
                "email": "jane.doe@example.com",
                "contact": "09170000009",
                "address": "Test Address",
                "gender": "Female",
                "password": "StrongPass123!",
                "confirm_password": "StrongPass123!",
                "role": "job_seeker",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["contact"][0], "This contact number is already in use.")

    @patch("user.views.send_mail")
    def test_register_sends_verification_email_and_normalizes_email(self, mock_send_mail):
        response = self.client.post(
            reverse("user"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "username": "janedoe",
                "email": "JANE.DOE@example.com",
                "contact": "09170000001",
                "address": "Test Address",
                "gender": "Female",
                "password": "StrongPass123!",
                "confirm_password": "StrongPass123!",
                "role": "job_seeker",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email"], "jane.doe@example.com")
        mock_send_mail.assert_called_once()
        self.assertEqual(mock_send_mail.call_args.kwargs["recipient_list"], ["jane.doe@example.com"])

    @patch("user.views.send_mail", side_effect=RuntimeError("SMTP failed"))
    def test_register_falls_back_in_debug_when_email_delivery_fails(self, mock_send_mail):
        response = self.client.post(
            reverse("user"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "username": "janedoe2",
                "email": "jane2.doe@example.com",
                "contact": "09170000002",
                "address": "Test Address",
                "gender": "Female",
                "password": "StrongPass123!",
                "confirm_password": "StrongPass123!",
                "role": "job_seeker",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email"], "jane2.doe@example.com")
        self.assertIn("verification_code", response.data)
        self.assertTrue(mock_send_mail.called)

    @patch("user.views.send_mail")
    def test_resend_signup_verification_uses_case_insensitive_email_lookup_and_sends_to_email_address(self, mock_send_mail):
        pending = SignupVerification.objects.create(
            email="jane.doe@example.com",
            payload={
                "first_name": "Jane",
                "last_name": "Doe",
                "username": "janedoe",
                "email": "jane.doe@example.com",
                "contact": "09170000001",
                "address": "Test Address",
                "gender": "Female",
                "password": "StrongPass123!",
                "role": "job_seeker",
            },
            code="123456",
        )

        response = self.client.post(
            reverse("resend-signup-verification"),
            {"email": "JANE.DOE@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        pending.refresh_from_db()
        self.assertNotEqual(pending.code, "123456")
        mock_send_mail.assert_called_once()
        self.assertEqual(mock_send_mail.call_args.kwargs["recipient_list"], ["jane.doe@example.com"])

    @patch("user.views.send_mail")
    def test_resend_email_verification_uses_case_insensitive_email_lookup_and_sends_to_email_address(self, mock_send_mail):
        user = CustomUser.objects.create_user(
            email="john.doe@example.com",
            username="johndoe",
            password="StrongPass123!",
            first_name="John",
            last_name="Doe",
            contact="09171234567",
            address="Test Address",
            gender="Male",
        )

        response = self.client.post(
            reverse("resend-email-verification"),
            {"email": "JOHN.DOE@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            PasswordResetOTP.objects.filter(
                user=user,
                purpose=PasswordResetOTP.PURPOSE_EMAIL_VERIFICATION,
            ).count(),
            1,
        )
        mock_send_mail.assert_called_once()
        self.assertEqual(mock_send_mail.call_args.kwargs["recipient_list"], [user.email])
