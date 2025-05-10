from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),

    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoices/<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/create/', views.create_invoice, name='create_invoice'),
    path('invoices/<int:invoice_id>/send/', views.send_invoice, name='send_invoice'),

    path('customers/', views.customer_list, name='customer_list'),
    path('customers/<int:customer_id>/', views.customer_detail, name='customer_detail'),

    path('tasks/<int:task_id>/', views.task_status, name='task_status'),
]
