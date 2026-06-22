"""Prueba MANUAL del módulo de agenda (Fase 1) — NO es un test automatizado.

Crea una cita de prueba, la busca por teléfono y la borra, contra el calendario real
configurado en CALENDAR_ID. Sirve para validar la Fase 0 (Calendar API habilitada +
calendario compartido con la SA) antes de cablear el tool-calling.

Requiere:
  - CALENDAR_ID en .env (o variable de entorno), compartido con la SA
    appvoz-voice@brainrot-walloop.iam.gserviceaccount.com (permiso "hacer cambios en eventos").
  - El JSON de la SA en backend/credentials/appvoz-voice.json.
  - Dependencia google-api-python-client instalada.

Ejecutar desde la raíz del repo:   python backend/_agenda_test.py
o dentro del contenedor:           docker compose exec api python _agenda_test.py
"""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.agenda import buscar_eventos, borrar_evento, crear_evento
from app.config import settings

TELEFONO = "+34600123456"   # número ficticio de prueba


async def main():
    cal = settings.calendar_id
    if not cal:
        raise SystemExit("Falta CALENDAR_ID (ponlo en .env y comparte el calendario con la SA).")

    tz = ZoneInfo(settings.agenda_timezone)
    # Mañana a las 17:00 hora local (prueba el manejo de zona/DST).
    manana = datetime.now(tz) + timedelta(days=1)
    inicio = manana.replace(hour=17, minute=0, second=0, microsecond=0)

    print(f"\n== 1) Crear cita ==  cal={cal}  inicio={inicio.isoformat()}")
    cita = await crear_evento(
        cal, inicio, duracion_min=30,
        resumen="Cita de prueba (AppVoz)",
        descripcion="Cita creada por _agenda_test.py",
        telefono=TELEFONO, nombre="Cliente Prueba",
        datos={"servicio": "corte"},
    )
    print("   ->", cita)
    event_id = cita["event_id"]

    print(f"\n== 2) Buscar por teléfono ==  {TELEFONO}")
    encontradas = await buscar_eventos(cal, TELEFONO)
    for c in encontradas:
        print("   ->", c)
    assert any(c["event_id"] == event_id for c in encontradas), "la cita creada no aparece en la búsqueda"

    print(f"\n== 3) Borrar cita ==  id={event_id}")
    ok = await borrar_evento(cal, event_id)
    print("   -> borrada:", ok)

    print("\n== 4) Verificar que ya no está ==")
    restantes = await buscar_eventos(cal, TELEFONO)
    assert not any(c["event_id"] == event_id for c in restantes), "la cita sigue tras borrar"
    print("   OK: la cita ya no aparece.\n")
    print("Prueba completada con éxito.")


if __name__ == "__main__":
    asyncio.run(main())
