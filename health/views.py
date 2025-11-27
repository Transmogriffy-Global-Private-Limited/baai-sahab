from django.http import JsonResponse
from django.db import connection
from datetime import datetime


def health_view(request):
    # Simple DB health check
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1;")
        row = cursor.fetchone()

    return JsonResponse(
        {
            "ok": True,
            "db": {
                "reachable": row == (1,),
            },
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    )
