# Demo for Django Async Manager 

This project demonstrates the capabilities of the `django_async_manager` library through a invoice management system. 

## Setup

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Apply migrations:
   ```
   python manage.py migrate
   ```
4. Run command to update beat schedule tasks:
   ```
   python manage.py update_beat_schedule
   ```
5. Run the development server:
   ```
   python manage.py runserver
   ```
6. In a separate terminal, run the task worker:
   ```
   python manage.py run_worker --queue invoices
   ```
7. In another terminal, run the scheduler (for periodic tasks):
   ```
   python manage.py run_scheduler
   ```
