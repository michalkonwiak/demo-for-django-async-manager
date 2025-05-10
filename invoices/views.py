from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.utils import timezone
from django.core.paginator import Paginator

from .models import Customer, Invoice, InvoiceItem
from .tasks import generate_invoice, send_invoice_email

def index(request):
    total_invoices = Invoice.objects.count()
    sent_invoices = Invoice.objects.filter(status='sent').count()
    recent_invoices = Invoice.objects.select_related('customer').order_by('-created_at')[:5]
    context = {
        'recent_invoices': recent_invoices,
        'total_invoices': total_invoices,
        'sent_invoices': sent_invoices,
    }
    
    return render(request, 'invoices/index.html', context)

def invoice_list(request):
    invoices = Invoice.objects.select_related('customer').order_by('-created_at')
    
    status_filter = request.GET.get('status')
    if status_filter and status_filter != 'all':
        invoices = invoices.filter(status=status_filter)
    
    paginator = Paginator(invoices, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter or 'all',
        'statuses': dict(Invoice.STATUS_CHOICES),
    }
    
    return render(request, 'invoices/invoice_list.html', context)

def invoice_detail(request, invoice_id):
    invoice = get_object_or_404(Invoice.objects.select_related('customer').prefetch_related('items'), id=invoice_id)
    
    context = {
        'invoice': invoice,
        'items': invoice.items.all(),
    }
    
    return render(request, 'invoices/invoice_detail.html', context)

def customer_list(request):
    customers = Customer.objects.all().order_by('name')
    
    context = {
        'customers': customers,
    }
    
    return render(request, 'invoices/customer_list.html', context)

def customer_detail(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    invoices = Invoice.objects.filter(customer=customer).order_by('-created_at')
    
    context = {
        'customer': customer,
        'invoices': invoices,
    }
    
    return render(request, 'invoices/customer_detail.html', context)

def create_invoice(request):
    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        
        items_data = []
        descriptions = request.POST.getlist('description')
        quantities = request.POST.getlist('quantity')
        unit_prices = request.POST.getlist('unit_price')
        
        for i in range(len(descriptions)):
            if descriptions[i] and quantities[i] and unit_prices[i]:
                items_data.append({
                    'description': descriptions[i],
                    'quantity': int(quantities[i]),
                    'unit_price': unit_prices[i]
                })
        
        task = generate_invoice(customer_id, items_data)
        
        messages.success(request, f'Invoice generation started (Task ID: {task.id})')
        return redirect('invoice_list')
    
    customers = Customer.objects.all().order_by('name')
    
    context = {
        'customers': customers,
    }
    
    return render(request, 'invoices/create_invoice.html', context)

@require_POST
def send_invoice(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)
    
    task = send_invoice_email(invoice_id)
    
    messages.success(request, f'Email sending started (Task ID: {task.id})')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'success', 'task_id': task.id})
    
    return redirect('invoice_detail', invoice_id=invoice_id)

def task_status(request, task_id):
    from django_async_manager.models import Task
    
    task = get_object_or_404(Task, id=task_id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'status': task.status,
            'created_at': task.created_at.isoformat(),
            'started_at': task.started_at.isoformat() if task.started_at else None,
            'completed_at': task.completed_at.isoformat() if task.completed_at else None,
            'error': task.error,
        })
    
    context = {
        'task': task,
    }
    
    return render(request, 'invoices/task_status.html', context)