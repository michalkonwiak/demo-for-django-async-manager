import logging
import random
import os
from datetime import datetime, timedelta
from decimal import Decimal
import json
import hashlib

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone
from django.core.exceptions import ValidationError

from django_async_manager.decorators import background_task
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from invoices.models import Customer, Invoice, InvoiceItem, Report

logger = logging.getLogger('task_worker')


def generate_invoice_number():
    prefix = "INV"
    timestamp = datetime.now().strftime("%Y%m%d")
    random_suffix = str(random.randint(1000, 9999))
    return f"{prefix}-{timestamp}-{random_suffix}"


@background_task(priority="high", queue="invoices")
def generate_invoice(customer_id, items_data=None, due_days=30):
    logger.info(f"Generating invoice for customer {customer_id}")

    try:
        customer = Customer.objects.get(id=customer_id)

        if not items_data:
            items_data = [
                {"description": "Service fee", "quantity": 1, "unit_price": Decimal("100.00")},
                {"description": "Consultation", "quantity": 2, "unit_price": Decimal("75.00")}
            ]

        total_amount = sum(
            Decimal(item["quantity"]) * Decimal(item["unit_price"])
            for item in items_data
        )

        invoice = Invoice.objects.create(
            invoice_number=generate_invoice_number(),
            customer=customer,
            issue_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=due_days),
            status='draft',
            total_amount=total_amount
        )

        for item_data in items_data:
            InvoiceItem.objects.create(
                invoice=invoice,
                description=item_data["description"],
                quantity=item_data["quantity"],
                unit_price=item_data["unit_price"]
            )

        logger.info(f"Successfully generated invoice {invoice.invoice_number}")
        return invoice

    except Customer.DoesNotExist:
        logger.error(f"Customer with ID {customer_id} does not exist")
        raise
    except Exception as e:
        logger.error(f"Error generating invoice: {str(e)}")
        raise



@background_task(priority="high", queue="invoices")
def validate_invoice_data(invoice_id):
    logger.info(f"Validating invoice data for invoice {invoice_id}")

    try:
        invoice = Invoice.objects.select_related('customer').prefetch_related('items').get(id=invoice_id)

        if not invoice.items.exists():
            logger.error(f"Invoice {invoice.invoice_number} has no items")
            raise ValidationError("Invoice has no items")

        if not invoice.customer.email:
            logger.error(f"Customer {invoice.customer.name} has no email address")
            raise ValidationError("Customer has no email address")

        calculated_total = sum(item.total for item in invoice.items.all())
        if abs(calculated_total - invoice.total_amount) > Decimal('0.01'):
            logger.error(f"Invoice {invoice.invoice_number} total amount mismatch: {invoice.total_amount} vs calculated {calculated_total}")
            raise ValidationError("Invoice total amount mismatch")

        if invoice.issue_date > invoice.due_date:
            logger.error(f"Invoice {invoice.invoice_number} issue date {invoice.issue_date} is after due date {invoice.due_date}")
            raise ValidationError("Invoice issue date is after due date")

        logger.info(f"Invoice {invoice.invoice_number} validation successful")
        return invoice

    except Invoice.DoesNotExist:
        logger.error(f"Invoice with ID {invoice_id} does not exist")
        raise
    except ValidationError as e:
        logger.error(f"Validation error for invoice {invoice_id}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error validating invoice {invoice_id}: {str(e)}")
        raise


@background_task(priority="high", queue="invoices")
def generate_invoice_pdf(invoice_id):
    logger.info(f"Generating PDF for invoice {invoice_id}")

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch

        invoice = Invoice.objects.select_related('customer').prefetch_related('items').get(id=invoice_id)

        pdf_dir = os.path.join(settings.BASE_DIR, 'invoice_pdfs')
        os.makedirs(pdf_dir, exist_ok=True)

        filename = f"invoice_{invoice.invoice_number.replace('-', '_')}.pdf"
        filepath = os.path.join(pdf_dir, filename)

        doc = SimpleDocTemplate(filepath, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        title_style = styles["Heading1"]
        elements.append(Paragraph(f"Invoice {invoice.invoice_number}", title_style))
        elements.append(Spacer(1, 0.25*inch))

        normal_style = styles["Normal"]
        elements.append(Paragraph(f"<b>Customer:</b> {invoice.customer.name}", normal_style))
        elements.append(Paragraph(f"<b>Email:</b> {invoice.customer.email}", normal_style))
        elements.append(Paragraph(f"<b>Address:</b> {invoice.customer.address}", normal_style))
        elements.append(Spacer(1, 0.1*inch))
        elements.append(Paragraph(f"<b>Issue Date:</b> {invoice.issue_date}", normal_style))
        elements.append(Paragraph(f"<b>Due Date:</b> {invoice.due_date}", normal_style))
        elements.append(Paragraph(f"<b>Status:</b> {invoice.get_status_display()}", normal_style))
        elements.append(Spacer(1, 0.25*inch))

        items_data = [["Description", "Quantity", "Unit Price", "Total"]]
        for item in invoice.items.all():
            items_data.append([
                item.description,
                str(item.quantity),
                f"${item.unit_price}",
                f"${item.total}"
            ])

        items_data.append(["", "", "Total:", f"${invoice.total_amount}"])

        table = Table(items_data, colWidths=[4*inch, 1*inch, 1.25*inch, 1.25*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -2), 1, colors.black),
            ('LINEBELOW', (0, -1), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(table)

        elements.append(Spacer(1, 0.5*inch))
        elements.append(Paragraph("Thank you!", normal_style))

        doc.build(elements)

        file_hash = hashlib.md5(open(filepath, 'rb').read()).hexdigest()

        logger.info(f"Successfully generated PDF for invoice {invoice.invoice_number} at {filepath}")
        return filepath

    except Invoice.DoesNotExist:
        logger.error(f"Invoice with ID {invoice_id} does not exist")
        raise
    except Exception as e:
        logger.error(f"Error generating PDF for invoice {invoice_id}: {str(e)}")
        raise


@background_task(priority="low", queue="invoices")
def log_email_activity(invoice_id, recipient_email=None, status="sent"):
    logger.info(f"Logging email activity for invoice {invoice_id}")

    try:
        invoice = Invoice.objects.select_related('customer').get(id=invoice_id)

        if recipient_email is None:
            recipient_email = invoice.customer.email

        log_entry = {
            "timestamp": timezone.now().isoformat(),
            "invoice_id": invoice_id,
            "invoice_number": invoice.invoice_number,
            "recipient": recipient_email,
            "status": status,
            "customer_id": invoice.customer_id,
            "amount": str(invoice.total_amount)
        }

        log_dir = os.path.join(settings.BASE_DIR, 'email_logs')
        os.makedirs(log_dir, exist_ok=True)

        log_file = os.path.join(log_dir, 'email_activity.log')
        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + "\n")

        logger.info(f"Successfully logged email activity for invoice {invoice.invoice_number}")
        return True

    except Invoice.DoesNotExist:
        logger.error(f"Invoice with ID {invoice_id} does not exist")
        raise
    except Exception as e:
        logger.error(f"Error logging email activity for invoice {invoice_id}: {str(e)}")
        raise


@background_task(priority="medium", queue="invoices")
def update_customer_communication_history(invoice_id, communication_type="email"):
    logger.info(f"Updating communication history for invoice {invoice_id}")

    try:
        invoice = Invoice.objects.select_related('customer').get(id=invoice_id)
        customer = invoice.customer
        customer_id = customer.id

        logger.info(f"Updating communication history for customer {customer.name} (ID: {customer_id})")

        comm_dir = os.path.join(settings.BASE_DIR, 'customer_communications')
        os.makedirs(comm_dir, exist_ok=True)

        customer_file = os.path.join(comm_dir, f'customer_{customer_id}.json')

        if os.path.exists(customer_file):
            with open(customer_file, 'r') as f:
                try:
                    history = json.load(f)
                except json.JSONDecodeError:
                    history = {"communications": []}
        else:
            history = {"communications": []}

        history["communications"].append({
            "timestamp": timezone.now().isoformat(),
            "type": communication_type,
            "invoice_id": invoice_id,
            "invoice_number": invoice.invoice_number,
            "amount": str(invoice.total_amount),
            "status": "sent"
        })

        with open(customer_file, 'w') as f:
            json.dump(history, f, indent=2)

        logger.info(f"Successfully updated communication history for customer {customer.name}")
        return True

    except Invoice.DoesNotExist:
        logger.error(f"Invoice with ID {invoice_id} does not exist")
        raise
    except Exception as e:
        logger.error(f"Error updating communication history for invoice {invoice_id}: {str(e)}")
        raise


@background_task(priority="medium", queue="invoices", 
                dependencies=[validate_invoice_data, generate_invoice_pdf, 
                             log_email_activity, update_customer_communication_history])
def send_invoice_email(invoice_id, document_path=None):
    logger.info(f"Sending invoice {invoice_id} via real email")

    try:
        from django_async_manager.models import Task
        invoice = Invoice.objects.select_related('customer').get(id=invoice_id)

        if document_path is None:
            try:
                recent_tasks = Task.objects.filter(name='send_invoice_email').order_by('-created_at')

                current_task = None
                for task in recent_tasks:
                    import json
                    try:
                        args = json.loads(task.arguments)
                        if args.get('args') and len(args['args']) > 0 and args['args'][0] == invoice_id:
                            current_task = task
                            break
                    except (json.JSONDecodeError, TypeError, IndexError):
                        continue

                if current_task:
                    pdf_task = current_task.dependencies.filter(name='generate_invoice_pdf').first()
                    if pdf_task and pdf_task.status == 'completed' and pdf_task.result:
                        document_path = pdf_task.result
                        logger.info(f"Retrieved document path from dependency: {document_path}")

                if document_path is None:
                    pdf_tasks = Task.objects.filter(
                        name='generate_invoice_pdf',
                        status='completed'
                    ).order_by('-completed_at')

                    for task in pdf_tasks:
                        try:
                            args = json.loads(task.arguments)
                            if args.get('args') and len(args['args']) > 0 and args['args'][0] == invoice_id:
                                document_path = task.result
                                logger.info(f"Retrieved document path from previous PDF task: {document_path}")
                                break
                        except (json.JSONDecodeError, TypeError, IndexError):
                            continue

                if document_path is None:
                    pdf_dir = os.path.join(settings.BASE_DIR, 'invoice_pdfs')
                    filename = f"invoice_{invoice.invoice_number.replace('-', '_')}.pdf"
                    expected_path = os.path.join(pdf_dir, filename)

                    if os.path.exists(expected_path):
                        document_path = expected_path
                        logger.info(f"Using expected document path: {document_path}")
            except Exception as e:
                logger.error(f"Error retrieving document path: {str(e)}")

        subject = f"Invoice {invoice.invoice_number}"

        body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Invoice {invoice.invoice_number}</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .header {{ text-align: center; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 1px solid #ddd; }}
                .invoice-details, .customer-details {{ margin-bottom: 20px; }}
                .total {{ text-align: right; font-weight: bold; margin-top: 20px; }}
                .footer {{ margin-top: 30px; font-size: 0.9em; text-align: center; color: #777; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Invoice</h1>
            </div>

            <div class="invoice-details">
                <p><strong>Invoice Number:</strong> {invoice.invoice_number}</p>
                <p><strong>Issue Date:</strong> {invoice.issue_date}</p>
                <p><strong>Due Date:</strong> {invoice.due_date}</p>
                <p><strong>Status:</strong> {invoice.status}</p>
            </div>

            <div class="customer-details">
                <h2>Customer Information</h2>
                <p><strong>Name:</strong> {invoice.customer.name}</p>
                <p><strong>Email:</strong> {invoice.customer.email}</p>
                <p><strong>Address:</strong> {invoice.customer.address}</p>
            </div>

            <div class="total">
                <p>Total Amount: ${invoice.total_amount}</p>
            </div>

            <div class="footer">
                <p>Thank you</p>
            </div>
        </body>
        </html>
        """

        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[settings.RECIPIENT_EMAIL],
        )
        email.content_subtype = 'html'

        if document_path:
            logger.info(f"Attaching document: {document_path}")
            email.attach_file(document_path)
        elif hasattr(invoice, 'pdf_file') and invoice.pdf_file:
            email.attach_file(invoice.pdf_file.path)

        email.send(fail_silently=False)

        invoice.status = 'sent'
        invoice.save()

        logger.info(f"Successfully sent invoice {invoice.invoice_number} to {settings.RECIPIENT_EMAIL}")
        logger.info(f"Document attached: {document_path if document_path else 'None'}")
        return True

    except Invoice.DoesNotExist:
        logger.error(f"Invoice with ID {invoice_id} does not exist")
        raise
    except Exception as e:
        logger.error(f"Error sending invoice email: {str(e)}")
        raise


@background_task(priority="medium",)
def generate_daily_invoice_report():
    logger.info("Starting daily invoice report generation")

    end_time = timezone.now()
    start_time = end_time - timedelta(days=1)
    recent_invoices = Invoice.objects.filter(
        created_at__gte=start_time,
        created_at__lt=end_time
    )

    reports_folder = os.path.join(settings.BASE_DIR, 'invoice_reports')
    os.makedirs(reports_folder, exist_ok=True)
    report_filename = f"daily_invoice_report_{end_time.strftime('%Y%m%d')}.pdf"
    report_path = os.path.join(reports_folder, report_filename)

    doc = SimpleDocTemplate(report_path, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Daily Invoice Report", styles['Heading1']))
    elements.append(Paragraph(f"Period: {start_time.date()} – {end_time.date()}", styles['Normal']))
    elements.append(Spacer(1, 0.2 * inch))

    table_data = [["Invoice #", "Issue Date", "Customer", "Amount", "Status"]]
    for inv in recent_invoices:
        table_data.append([
            inv.invoice_number,
            str(inv.issue_date),
            inv.customer.name,
            f"{inv.total_amount:.2f}",
            inv.get_status_display()
        ])

    table = Table(table_data, colWidths=[1.5*inch, 1.5*inch, 2.5*inch, 1*inch, 1*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("End of report", styles['Normal']))

    doc.build(elements)
    logger.info(f"PDF saved at: {report_path}")

    subject = "Daily Invoice Report"
    body = "Please find attached the invoice report for the last 24 hours."
    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[settings.RECIPIENT_EMAIL],
    )
    email.attach_file(report_path)
    email.send(fail_silently=False)
    logger.info(f"Report emailed to: {settings.RECIPIENT_EMAIL}")

    return report_path