# AGENTS.md — Punto de Entrada Obligatorio para IAs (Claude Code, Codex, Windsurf)

> **Este archivo es solo un puntero.** Toda la memoria, reglas y contexto viven en los archivos
> de la raíz y en `/docs/`. Cualquier IA que opere aquí DEBE leerlos ANTES de escribir una sola
> línea de código.

## Orden de lectura obligatorio (en este orden)

1. **`SYSTEM_PROMPT.md`** — identidad de la IA, stack tecnológico exacto y reglas estrictas
   (rieles inquebrantables: no tocar harnesses, causalidad, loop Karpathy, probabilidad vs etiquetas).
2. **`SPECS.md`** — plano funcional: universos de activos, motores cuantitativos (Engine A rough vol,
   Engine B market-neutral, saltos HAR), gates de validación y fuera de alcance.
3. **`TODO.md`** — ejecutar SOLO la tarea marcada `[EN CURSO]` o la que el usuario indique.
   Al terminar: marcar `[COMPLETADO]` y detenerse.
4. **`HANDOFF.md`** — estado actual, récords vigentes, qué funciona, qué quedó a medias.
   Al cerrar sesión: actualizarlo para el relevo sin pérdida de contexto.
5. **`/docs/`** — base de conocimiento detallada:
   - `docs/project-brief.md` (visión, tesis de inversión, universo de activos)
   - `docs/tech-stack.md` (librerías, versiones, comandos, entorno)
   - `docs/product-features.md` (catálogo exhaustivo de features y modelos)
   - `docs/system-architecture.md` (flujos de datos, arnés, loops, contratos)
   - `docs/code-guidelines.md` (estándares, patrones requeridos y prohibidos)
   - `docs/progress.md` (récords, ledger de trials, lecciones aprendidas)
6. **Referencias técnicas complementarias**: `SYSTEM.md` (arquitectura operativa + comandos),
   `.agent.md` (catálogo de `research/` con 114 notebooks y recetas extraídas),
   `program.md` (instrucciones específicas del loop crypto).

## Regla de actualización (Vibe Coding)

- **Al INICIO de cada tarea**: leer `SPECS.md` + `TODO.md`. Marcar la tarea `[EN CURSO]`.
- **Al FINAL de cada tarea**: actualizar `TODO.md` (`[COMPLETADO]`) y `HANDOFF.md`
  (qué cambió, métricas exactas, siguiente paso). No editar archivos innecesarios.
- **Solo hay que editar `SYSTEM_PROMPT.md`** para reglas globales nuevas, y `docs/`
  cuando cambien: stack, features nuevas, arquitectura o alcance.

## Tarea pendiente de referencia

Consulta la primera tarea `[ ]` de `TODO.md`. Ejemplo de prompt a usar:

> "Lee `SYSTEM_PROMPT.md`, `SPECS.md` y `TODO.md`. Realiza la tarea `[EN CURSO]` actual.
> Al finalizar, marca `[COMPLETADO]` en `TODO.md`, actualiza `HANDOFF.md` y detente.
> No edites archivos innecesarios."
