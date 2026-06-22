"""Prueba MANUAL del onboarding 4G (extracción + Canva), SIN voz — no es test automatizado.

Valida la parte determinista: extracción por sección con Flash, la compuerta
`seccion_completa`, y la persistencia del Canva (tabla canva_4g). La voz se prueba aparte
en el navegador (/4g).

Ejecutar dentro del contenedor:  docker compose exec api python _4g_test.py
"""
import asyncio

from app import canva4g

FECHA = "jueves 18/06/2026 23:00 (Europe/Madrid)"


async def main():
    print("== 1) Extracción VISIÓN ==")
    conv_v = ("\nGuía: ¿qué harías diferente si supieras que mañana mueres?"
              "\nPersona: querría ser un padre presente, crear una empresa que ayude a la "
              "gente y tener salud y tiempo para mi familia.")
    v = await canva4g.extraer_seccion("vision", conv_v, FECHA)
    print("   ->", v, "| completa:", canva4g.seccion_completa(canva4g.SECCIONES_POR_KEY["vision"], v))

    print("\n== 2) Extracción VALORES (lista) ==")
    conv_val = ("\nGuía: ¿qué principios guían tus decisiones?"
                "\nPersona: la honestidad, porque sin confianza no hay nada; y la familia, "
                "que va primero.")
    val = await canva4g.extraer_seccion("valores", conv_val, FECHA)
    print("   ->", val, "| completa:", canva4g.seccion_completa(canva4g.SECCIONES_POR_KEY["valores"], val))

    print("\n== 3) Extracción BLOQUE (fecha relativa → ISO) ==")
    conv_b = ("\nGuía: ¿para qué rol quieres tu primer bloque y qué día?"
              "\nPersona: para el rol de padre, el próximo lunes a las seis de la tarde.")
    b = await canva4g.extraer_seccion("bloque", conv_b, FECHA)
    print("   ->", b, "| completa:", canva4g.seccion_completa(canva4g.SECCIONES_POR_KEY["bloque"], b))

    print("\n== 4) Persistencia del Canva (tabla canva_4g) ==")
    await canva4g.guardar_canva("test-4g", {"vision": v, "valores": val, "bloque": b})
    got = await canva4g.obtener_canva("test-4g")
    print("   guardado/leído ->", got)
    print("   primera_incompleta:", canva4g.primera_incompleta(got), "/", len(canva4g.SECCIONES))
    print("\nPrueba 4G (determinista) completada.")


if __name__ == "__main__":
    asyncio.run(main())
