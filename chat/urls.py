from django.urls import path
from . import views

urlpatterns = [
    path("messages/", views.create_message_view, name="chat-create-message"),
    path("messages/list/", views.list_messages_view, name="chat-list-messages"),
    path("messages/<int:message_id>/", views.edit_message_view, name="chat-edit-message"),
    path("messages/<int:message_id>/delete/", views.delete_message_view, name="chat-delete-message"),
    path("messages/<int:message_id>/seen/", views.mark_seen_view, name="chat-mark-seen"),
]
