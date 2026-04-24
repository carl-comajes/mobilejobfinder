from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Application, CustomUser, Job


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    model = CustomUser
    list_display = ("email", "username", "first_name", "last_name", "is_staff")
    list_filter = ("is_staff", "is_superuser", "gender")
    ordering = ("email",)
    search_fields = ("email", "username", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        ("Personal info", {"fields": ("first_name", "middle_name", "last_name", "contact", "address", "gender")}),
        ("Company info", {"fields": ("company", "company_description", "industry", "is_recruiter")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "username", "first_name", "last_name", "contact", "address", "gender", "company", "company_description", "industry", "password1", "password2"),
            },
        ),
    )


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "location", "job_type", "created_by", "created_at")
    search_fields = ("title", "company", "location")
    list_filter = ("job_type", "created_at")


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("full_name", "job", "email", "phone", "status", "created_at")
    search_fields = ("full_name", "email", "job__title", "job__company")
    list_filter = ("status", "created_at")
