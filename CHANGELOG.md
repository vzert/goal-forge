# Changelog

All notable changes to the `goalspec` plugin. This project follows
[semantic versioning](https://semver.org/). **Bump `plugins/goalspec/.claude-plugin/plugin.json`
`version` on every release** — the install cache is keyed by version
(`~/.claude/plugins/cache/goal-forge/goalspec/<version>/`), so changes pushed without a
version bump are never delivered to already-installed users.

## [0.30.0] - 2026-07-30

**Un `[COMPLETION-REVIEW: ...]` cierra el spec, no la sesión** — hallazgo Alta de un audit contra
el JSONL real de un incidente de usuario (dev externo, sesión real; detalle no shippeado, vive en
memoria privada del proyecto). Un ciclo formal de goalspec cerró limpio cubriendo dos PRs a
`develop`; la MISMA sesión siguió después con 3 releases reales a producción y, más serio, con el
agente investigando por su cuenta tras el cierre, concluyendo un hallazgo falso (error propio de
timezone), y **escribiéndolo y pusheándolo a memoria compartida** que otros agentes leen como
hecho — antes de que el humano pudiera confirmarlo o objetar. Nada en `SKILL.md` distinguía
"spec cerrado" de "sesión terminada", así que ninguna disciplina (clarify/ratify/adversario)
se re-disparó para la parte de mayor riesgo real de la sesión.

**Decisión de alcance, vía `/goalspec:interview`** (entrevista de 2 rondas, 6 forks resueltos):
fix **solo documentado**, sin hook/matcher nuevo — el proyecto ya tiene tres instancias de
"matcher más listo" que perdieron la carrera de heurísticas (id-matcher roto 5 rondas en v0.11.1,
sub-conteo del convergence-floor por dedup literal, ceguera del floor dentro de una secuencia
agéntica sin `Stop` entre rondas). Carrier híbrido: regla corta en el cuerpo de `SKILL.md`
(visible en cada corrida) + rationale completo en un archivo nuevo dedicado.

**Qué cambió**: `skills/goalspec/SKILL.md` gana (1) un ejemplo nombrado en la lista de acción
terminal — escribir una conclusión propia no confirmada a estado/memoria compartida, aunque no
mute código — y (2) una subsección nueva ("A completion-review closes the spec, not the
session") que nombra el límite y prescribe **re-entrada dirigida**: si surge una acción
terminal-class nueva más tarde en la misma sesión, es un disparador fresco **con su propio
objetivo/alcance** — no se dobla dentro del spec ya cerrado, aunque esté relacionado; lo único
que se reusa es el contexto (repo, cuenta, hechos ya asentados), nunca la autorización. Ir directo
a 4b (ratify), nombrando el objetivo/alcance de ESTA acción, + 6 (adversario), sin reiniciar
clarify para lo que nada aquí pone en duda — y cerrar el ciclo re-entrado declarando un
`[COMPLETION-REVIEW: ...]` **fresco** para esa acción (el gate solo lee la declaración más
reciente de la sesión; una del ciclo anterior no puede representar una acción que nunca vio).
`references/mid-session-retrigger.md` (nuevo) documenta el caso, el porqué de la vía documentada
sobre la mecánica, qué significa la re-entrada dirigida, y qué queda explícitamente sin cubrir —
incluyendo, con honestidad, que el propio gate mecánico no distingue una declaración vieja de una
que realmente cubre la acción nueva; si el ejecutor omite la declaración fresca, el gate queda en
silencio igual que con cualquier otra regla solo-documentada de este método.

## [0.29.0] - 2026-07-30

**Fin de vida para `.goalspec/checkpoint.md`** (resuelve el pendiente ALTA creado 2026-07-30).
Un leftover de una sesión ya CERRADA y shippeada (v0.28.0, `f148d6c`) quedó en un working
directory e hizo que `hooks/nudge-decompose.sh` disparara su nudge advisory en CADA turno de una
sesión posterior no relacionada — el hook nunca tuvo noción de si el archivo pertenecía a ESA
sesión. `references/durable-artifact.md` decía cuándo crearlo, nunca cuándo borrarlo.

**Decisión, no config**: se evaluaron (a) instrucción de limpieza al cierre, y (b) que el propio
hook detecte staleness (mtime o un id de sesión/transcript exacto-matcheado contra el archivo).
(a) se adoptó; (b) se consideró explícitamente y se declinó — no por imposible (un id de sesión
exacto-matcheado, la misma disciplina que ya aplica `nudge-decompose.sh` a `subagent_type`,
funcionaría y además cubriría el caso de un crash sin resumir) sino porque agrega un contrato de
contenido nuevo + lógica read-side nueva para cerrar un hueco con exactamente UNA ocurrencia
confirmada, que fue un cierre limpio. Retiro write-side no necesita ninguna de las dos cosas. La
razón queda escrita en `references/durable-artifact.md` ("When it goes away") para que una sesión
futura no la re-litigue sin un segundo incidente que pese contra ese costo.

**Qué cambió**: `references/durable-artifact.md` gana una sección nueva que manda borrar el
archivo (no solo su contenido) al cierre limpio — con una excepción explícita para el proyecto que
deliberadamente comitea `.goalspec/` como trail — y documenta qué queda sin cubrir (un leftover de
una sesión que crasheó y nunca se resumió). `skills/goalspec/SKILL.md` (paso 7) y
`skills/adversary/SKILL.md` (paso 5, el comando standalone que no tiene paso 7 propio) ahora
instruyen el borrado en sus dos caminos de escritura reales (paso 5 y paso 6 del loop principal;
paso 2 del standalone). `hooks/nudge-decompose.sh` no cambió ninguna rama de control — solo su
mensaje advisory, que ahora nombra la mitigación directamente para un humano que lea un
falso-positivo. `test/decompose-nudge-branches.py` suma el caso 16 (contenido del mensaje, no solo
nudge/silent — el único caso capaz de probar el único cambio mecánico real de este fix en ese
hook). `CLAUDE.md` corrige "las cuatro suites" a "las cinco" (la quinta, `decompose-nudge-branches.py`,
existe desde v0.28.0 pero nunca se agregó a esa instrucción).

**Dos rondas de adversario, ambos backends, contra la META-edición** (dogfooding obligatorio del
proyecto): **ronda 1** (subagente, `claude-opus-5`, `model=different` vs. mi `claude-sonnet-5`) —
`break incomplete=3`: (1) nunca posteé un bloque `## Goal-spec` real antes de tocar código —
razoné la decisión (a)-vs-(b) internamente pero violé la instrucción explícita del usuario de
"decide antes de tocar código"; el gate quedó desarmado toda la sesión; (2) el paso 7 de
`SKILL.md` condicionaba el borrado solo a "(paso 5)", dejando sin cubrir el camino de escritura
independiente del paso 6; (3) `durable-artifact.md` tenía una contradicción sin reconciliar entre
"puede comitear para trail" y "borrar siempre al cierre". El backend externo (codex) falló con
auth token invalidado — `UNVERIFIED`, no contado. Se posteó el `## Goal-spec` (tarde, con la
violación de orden divulgada explícitamente — no se puede deshacer) y se corrigieron (2) y (3).
**Ronda 2** (ambos backends, codex ya reautenticado): el subagente (`claude-opus-5` de nuevo,
re-derivación completa, git-sha pineado) devolvió `hold` limpio sobre el árbol post-fix. El externo
(`GPT-5`) devolvió `break incomplete=3` — pero sobre una foto DEL ÁRBOL ANTERIOR al fix de (2)/(3)
(un race de timing entre las dos rondas paralelas), confirmado stale por la propia re-derivación
del subagente contra el mismo git diff; su hallazgo (1) es el mismo hecho histórico no corregible
ya divulgado en la ronda 1. El propio hold de la ronda 2 señaló un riesgo de autonomía real antes
de cerrar: el goal-spec afirmaba "ninguna otra decisión es del usuario" en el mismo párrafo que
divulgaba haber violado su instrucción de orden — se lo pregunté al usuario antes de shippear
("shippear igual" vs. revisar el diff vs. rehacer limpio); eligió shippear.

## [0.28.0] - 2026-07-29

**Fase 2 del plan de remediación del trigger de decomposición — nudge mecánico no-bloqueante
(`memory/plans/plan-trigger-decomposicion.md`).** Fase 1 (v0.27.0) reubicó y simplificó el texto
del trigger de decomposición en `SKILL.md`; no le dio ningún consumidor mecánico —
`gate-goal-close.sh` seguía sin ningún check funcional para la señal. Este release cierra ese hueco
con un hook nuevo, `hooks/nudge-decompose.sh`, registrado como `Stop` hook (tercero en `hooks.json`,
junto a `gate-goal-close.sh` y `check-usage-budget.sh`).

**Diseño, resuelto por grounding, no por pregunta al operador** (dos forks quedaban abiertos en el
plan): el punto de disparo tenía que ser `Stop`, no `PostToolUse` sobre `Task|Agent` — un
`PostToolUse` con ese matcher solo se dispara cuando SÍ hubo una llamada a `Task`/`Agent`, así que
estructuralmente no puede detectar su *ausencia*; solo `Stop` tiene visibilidad de la sesión
completa (mismo patrón que `check-usage-budget.sh`). La señal elegida: `.goalspec/checkpoint.md`
presente en el cwd, con un heading `## Coverage-floor table` y una tabla markdown de ≥2 filas de
datos, Y cero `tool_use` con `name` `Task`/`Agent` **que dispare un worker de entidad** — ver el
break del adversario abajo — en todo el transcript. `checkpoint.md` es opcional por diseño
(`references/durable-artifact.md`: "never create it speculatively"), así que su sola presencia con
una tabla poblada ya es la propia afirmación del agente de que identificó ≥2 entidades — el hook no
intenta parsear la enumeración de coverage-floor de prosa libre en el transcript (sin forma fija, no
parseable de forma confiable); mira el único lugar donde el método ya la pide de forma estructurada.

**Nunca un gate**: el hook nunca emite `decision:block`, nunca lee `GOAL_GATE_ENFORCE` — no tiene
rama de enforce en absoluto, por diseño (ratificado: "cualquier gate bloqueante" estaba
explícitamente fuera de alcance). Tampoco afirma independencia probada: el mensaje dice
explícitamente que es un proxy estructural — una tabla de ≥2 filas puede enumerar otra cosa que
entidades de ejecución decomponibles (ej. los carriers de un rule-surface sweep, forma real
encontrada en vivo en el propio `.goalspec/checkpoint.md` histórico de este repo).

**Break real del adversario (subagente, Opus vs. mi Sonnet 5, `model=different` — degradado a
`model=same` en el completion-review por el bug conocido de corchetes anidados en
`gate-goal-close.sh`, ver pendiente 2026-07-28) — 1 hallazgo `ungrounded` + 1 `unfalsified` + 3
`incomplete`, los 5 corregidos antes de cerrar**:
1. **Ungrounded — el borrador original contaba CUALQUIER `Task`/`Agent` como "ya decompuso",
   incluyendo el propio spawn del adversario del paso 6.** El paso 6 de `SKILL.md` manda escribir
   el checkpoint y LUEGO spawnear el adversario apuntando a él — exactamente la secuencia que puebla
   la tabla de coverage-floor y produce un `Agent` tool_use en el mismo aliento, cerrando la ventana
   del nudge en casi cualquier corrida checkpointeada real. Verificado en vivo: el hook contra el
   checkpoint real de esta sesión y un transcript sin adversario emitía el nudge; el mismo hook,
   mismo checkpoint, contra el transcript real de esta sesión (que sí incluye el spawn del
   adversario) quedaba en silencio. **Corregido**: un `Task`/`Agent` cuyo `subagent_type` nombra al
   adversario ya NO cuenta como decomposición — `nudge-decompose.sh` step 3 lo excluye
   explícitamente; 3 casos nuevos en la suite (07/08/09) lo pinnean.
2. **Unfalsified**: el pre-mortem #3 del checkpoint afirmaba "esta sesión no decompuso, así que el
   próximo Stop debería nudgear" — falso en el momento en que se escribió, porque el propio spawn
   del adversario (necesario para verificarlo) ya contaba como decomposición bajo el diseño viejo.
   Se resuelve solo con el fix del punto 1.
3. **Incomplete — `references/durable-artifact.md:8-9`** afirmaba "no hook parses it [checkpoint.md]"
   sin excepción; ahora falso. Corregido: se documenta `nudge-decompose.sh` como segundo lector
   acotado (solo cuenta filas, nunca confía en el texto de estado de una fila).
4. **Incomplete — inventario de hooks en `README.md`** no listaba el hook nuevo. Corregido.
5. **Incomplete — el sweep mecánico de decisiones heredadas nunca se corrió esta sesión**: la
   pendiente `memory/_pendientes.md` (fila "Observar en vivo (a) la decomposición S5c...") toca
   directamente esta señal y no fue citada. Corregido: nota cruzada agregada.

**Break real del adversario externo (codex/GPT-5, re-verificación de la ronda anterior —
`adversary.backend=external` resuelto de config; la ronda 1 había corrido solo el subagente, esta
ronda corrigió eso) — 1 `ungrounded` + 1 `unfalsified` + 3 `incomplete`, los 5 corregidos**:
1. **Ungrounded — el fix de la ronda 1 usaba un test de SUBSTRING (`"adversary" in subagent_type`)**,
   gameable por cualquier worker real cuyo `subagent_type` simplemente contenga esa palabra sin ser
   uno de los dos nombres exactos conocidos (ej. `not-goal-adversary-example`) — probado en vivo:
   producía `nudge` en vez de `silent`, clasificando mal una decomposición real como spawn de
   adversario. **Corregido**: match exacto (case-insensitive, trim) contra
   `{"goal-adversary", "goalspec:goal-adversary"}` — misma lección que `gate-goal-close.sh` ya
   aplica al matching de `ADVERSARY-MODEL` (posicional/exacto, nunca substring fabricado).
2. **Unfalsified/incomplete**: referencias obsoletas a "10 casos" en `.goalspec/checkpoint.md` y a
   "requiere cero `Task`/`Agent` en cualquier parte" en `test/README.md`, ambas contradichas por la
   exclusión ya shippeada. Corregidas.
3. **Incomplete**: sin caso de control para la colisión de substring exhibida en el punto 1.
   Corregido: caso nuevo `10-substring-collision-still-silences`.

**Segundo break real, externo (mismo backend, re-verificación de la ronda 2) — 1 `ungrounded` +
1 `unfalsified` + 2 `incomplete` + 1 `autonomy-violations`, los 5 corregidos**:
1. **Ungrounded**: un `transcript_path` ausente o apuntando a un archivo inexistente se trataba como
   "cero decomposición" y emitía el nudge, contradiciendo la propia promesa del hook ("cualquier
   falla de lectura/parseo es fail-open y silenciosa"). **Corregido**: ausencia/no-legibilidad del
   transcript ahora resuelve a silencioso — "no puedo determinar si hubo decomposición" no es lo
   mismo que "no hubo decomposición". Caso nuevo `15-missing-transcript-silent`.
2. **Incomplete**: este mismo CHANGELOG seguía diciendo "13 casos" con la suite y el checkpoint ya
   en 14. Corregido (ahora 15, tras el fix del punto 1).
3. **Autonomy**: la fila de la tabla de coverage-floor de `.goalspec/checkpoint.md` sobre el push
   podía leerse como "autorización ya pedida", cuando en realidad aún no se había pedido — el
   transcript real solo tiene la pregunta de proceso (interview vs. loop directo), ninguna sobre
   push. Corregido: reformulada sin ambigüedad, y la autorización se pide de verdad en este turno de
   cierre, no narrada como ya resuelta.

**Convergencia**: 3 rondas consecutivas de `break` (subagente, externo, externo) — el piso de
convergencia del método. Cada una rompió algo más chico que la anterior (ventana cero del nudge →
detalle de matching del fix → higiene de fail-open/docs), ninguna revirtió el fix de la ronda
previa, así que no es un patrón de "el diseño está mal" sino de hallazgos reales decrecientes. Por
disciplina del método, esta sesión NO lanzó una cuarta ronda de adversario persiguiendo un veredicto
limpio — se aplicaron los 3 fixes (todos mecánicos, ninguno de diseño) y se cerró pidiendo
autorización real de push al humano, sin re-verificar una cuarta vez.

**Verificación**: `test/decompose-nudge-branches.py` nuevo, 15 casos — guard de re-entrada
(`stop_hook_active`), controles que prueban que la ausencia de `Task`/`Agent` se chequea de verdad
(con decomposición vía `Agent` y vía `Task`, ambos silencian; una tool no relacionada como
`Bash`/`Read` no cuenta como decomposición), 3 casos que pinnean la exclusión del spawn del
adversario, 1 caso de control de colisión de substring, 4 controles que prueban que el conteo de
filas y la detección del heading son reales y no un "checkpoint existe → nudge" hardcodeado (1 fila,
0 filas, sin checkpoint, checkpoint sin el heading), y 1 caso de fail-open sobre transcript
ausente/no-legible. Las 5 suites (las 4 existentes + esta) exit 0, incluyendo `gate-branches.py`
bajo `GOAL_GATE_ENFORCE=1`; `claude plugin validate` exit 0 (exit code real, no `| tail`).
`plugin.json` + `marketplace.json` → 0.28.0 (sincronizados); `test/README.md` documenta la suite
nueva.

**Lo que esta suite NO cubre** (documentado explícitamente, no implícito en el verde): una sesión
real donde la tabla de coverage-floor se pobló y la decomposición de ENTIDADES DE EJECUCIÓN
genuinamente se saltó no se observó en vivo — cada caso de la suite maneja el hook directamente con
un checkpoint y transcript sintéticos, el mismo patrón hermético que `usage-budget-branches.py` ya
usa para su propio hook. Queda como observación abierta, no como algo que este release cierra. Lo
que SÍ se observó en vivo, y fue justo lo que encontró el primer break del adversario (subagente,
punto 1 de esa ronda): el hook real contra el transcript real de esta misma sesión de cierre (que sí
incluye un spawn del adversario) — esa observación en vivo es la que expuso el defecto, no algo que
este release deje sin probar.

## [0.27.0] - 2026-07-28

**Fase 1 del plan de remediación del trigger de decomposición — reubicación + simplificación, sin
código nuevo.** El grounding audit de una investigación de contexto (un usuario reportó "consumió
1M de tokens y se detuvo" — el forense del transcript real mostró que NO fue eso: pico real 582,815
tokens, la sesión sí terminó, el checkpoint sí recuperó post-compact; ver
`memory/research/2026-07-28-context-exhaustion-live-case.md` en el repo de trabajo, no versionado)
encontró un defecto real e independiente en `SKILL.md`: la guía "decompose execution when the
entities are independent" (introducida en v0.12.0) estaba enmarcada como check de CIERRE
("before declaring complete" / "before considering the objective met"), así que un agente que la
lee como verificación final llega a la instrucción de decomponer cuando el contexto ya se gastó —
y una de sus dos condiciones ("the task is long enough to risk one context filling up before it's
done") es estructuralmente inmedible, ya que ningún hook ni el propio agente puede leer el % real
de contexto usado (confirmado por `references/usage-budget-setup.md` y el propio historial de este
CHANGELOG). Fix, vía `/goalspec:interview` + el loop completo: (1) la cláusula inmedible se retira
por completo — decompón siempre que las entidades enumeradas sean independientes, sin condición de
tamaño. **No es un riesgo ya acotado — es un tradeoff aceptado a propósito**: a la interview se le
ofreció explícitamente la alternativa de un proxy medible (umbral contable de N entidades) y se
eligió quitar la condición sin reemplazo; el efecto real es que una tarea multi-entidad chica (ej.
un PR de 3 archivos) ahora SÍ decompone en 3 subagentes donde antes la cláusula de tamaño podía
evitarlo — "coverage floor" acota *multiplicidad* de entidades, no *tamaño* de tarea, y son ejes
ortogonales (hallazgo del adversario subagente, ronda 1: el primer borrador de este párrafo
confundía ambos ejes al justificar el cambio); (2) el momento de decidir se mueve de "antes de
declarar completo" a "en cuanto enumerás las
entidades" (usualmente al armar el spec, no al cerrar) en dos carriers — el bullet de coverage-floor
(`SKILL.md` sección "cuatro patrones derivados") y el paso 5 (Execute) del loop. Rule-surface
enumeration corrida sobre todo el repo, en dos rondas (el adversario externo rompió dos veces sobre
esto: primero un barrido acotado a `plugins/goalspec/` + `README.md` que se saltó `CHANGELOG.md`
entero; después un recuento sin `grep -n` línea por línea que dijo "2" cuando eran 3): `SKILL.md`
es el único carrier leído como guía de comportamiento actual, y es el único editado; `README.md`'s
dos menciones son punteros genéricos sin la cláusula; `CHANGELOG.md` la carga 3 veces (v0.12.0,
v0.17.0, esta misma entrada) y las 3 quedan explícitamente exentas como registro histórico
append-only (nunca se reeditan retroactivamente). Cero código nuevo —
el nudge mecánico no-bloqueante (que le daría un consumidor real a la señal de
decomposición/checkpoint) queda documentado como Fase 2 en `memory/plans/` (no versionado), fuera
del alcance de esta release.

## [0.26.0] - 2026-07-27

**Guided interview command — `/goalspec:interview`.** User-reported failure mode upstream of the
whole method: when the initial description is too thin, the loop's clarify step — one batched
modal over the forks the agent can already *name* — produces a spec that is grounded, falsifiable,
and aimed at the wrong objective, because with structurally underspecified intent the load-bearing
forks only become visible as earlier answers land. Prior art studied before building:
mattpocock/skills' grilling family (`grilling` / `grill-me` / `batch-grill-me`); **adapted, not
adopted** — what survived is the decision-tree-walked-in-dependency-order interview and the
facts-vs-decisions split (which the constitution's Autonomy principle already carried); what was
deliberately left behind is one-question-at-a-time conversational mode (frontier rounds map
better to `AskUserQuestion` and converge faster), ADR/glossary capture (repo-centric; the
goal-spec is already the durable record), their PRD template (the 6-question scaffold is
stronger), and question caps (rejected there for reasons that hold here). Shipped as a third
**thin** skill (`skills/interview/SKILL.md`) plus **one routing addition to the main skill's
clarify step** (its home, echoed once in runbook step 2): structural can't-articulate ambiguity
escalates to the interview instead of stretching the single batched modal — added because the
trigger acid test showed the main skill's own description winning the turn-1 skill-selection race
on exactly the utterances this command exists for, so without a yield clause at that junction the
interview would systematically never fire. Hooks, gate, and the `goal-adversary` definition
untouched:

- **What it does**: frames the ask as a decision tree and interviews in **rounds of one
  `AskUserQuestion` modal each**, carrying only the current **frontier** — decisions whose
  prerequisites are already settled (≤4 questions, most load-bearing first). Facts are never
  asked: anything lookable is resolved by the agent, sized exactly as the grounding step sizes
  acquisitions; an in-flight lookup only holds back its downstream questions. Every question is
  a load-bearing fork (plausible answers → genuinely different work) with a "(Recommended)"
  option first — the batching/default rules' home stays the main skill's clarify section,
  referenced rather than restated. An "Other" free-text answer is treated as evidence the fork's
  framing is wrong, not as a fifth option.
- **Termination without a cap**: done when the frontier is empty. Two guards instead of a
  counter: once objective-level forks settle, an explicit "Proceed with what we have" option
  makes continuing the user's choice (whatever is unsettled travels into the spec's Assumptions
  line, not into silence); and a frontier that *grows* round over round is surfaced as a fork
  (narrow to one branch vs. scope the effort first), never ground through.
- **Handoff with mechanical teeth**: the settled understanding is the input to the full loop —
  the clarify step should find nothing left to ask, and the spec must **visibly reflect** the
  interview (if the spec that comes out is the one you'd have written anyway, the ask was never
  underspecified). The interview itself is stateless; the `## Goal-spec` that follows is the
  durable record.
- **Gate deliberately unarmed, ratify untouched**: the command emits no `## Goal-spec`, adds no
  markers/gates/matchers, and explicitly does not replace step 4b — settling *intent* upstream
  is not approving *the spec that intent becomes*, so the ratify gate still fires on blast
  radius later. Headless/`-p`: an interview is interactive by definition — the skill states it
  does not apply and falls back to the loop's normal headless path.
- **Trigger, acid-tested three ways** (headless `claude -p` runs in throwaway dirs, byte-identical
  skill copy, invocation read from the stream-json transcript): a clear terse request does **not**
  invoke the interview (2/2 runs, zero false positives); an explicit **"interview me about it"**
  invokes it directly as the first tool of the turn (1/1); a plain **"I don't know how to explain
  what I need"** loses the turn-1 skill-selection race to the main goalspec skill's own description
  (2/2, measured before and after adding a precedence clause to the interview description — the
  clause alone does not win) and is exactly why the clarify-step routing sentence exists: on 0.26.0
  that utterance reaches the interview *through the loop* (goalspec triggers → clarify escalates,
  interactive sessions only). The escalation branch runs from the installed skill body and is
  interactive by definition, so it is not headless-measurable — stated here rather than claimed
  tested.

## [0.25.0] - 2026-07-27

**The claim-naming vs. narration boundary, drawn where the tension lived.** The 0.24.0 closing
round's one residual break (`incomplete=1`, ratified as shippable residue by the operator) was a
real tension in `skills/adversary/SKILL.md`'s own text: step 1 orders "name the claimed outcome"
while step 3's No-narration bullet prohibited restating conversation state — without saying which
side a payload that *opens by naming the claim* falls on. A strict external verifier read a
~95%-conform payload as prohibited narration for exactly that gap. This release adds the missing
boundary sentence to the No-narration bullet: **naming the claim under verification — step 1's
one sentence plus its paths — IS the command's object, not narration; narration is conversation
state beyond the claim and its paths.** One sentence in one carrier, nothing else touched — the
payload contract's home (the main skill's step 6) carries no claim-naming instruction (there the
written goal-spec is the claim, pointed at by path), the `goal-adversary` definition already
routes handed narration to the artifact it describes, and the hooks are unchanged (rule-surface
enumeration run; each other carrier exempt for the reason just named).

**Standalone adversary command — `/goalspec:adversary`.** Operator-requested after a session ran
the adversary six times *outside* the full loop and it kept catching real defects: the verifier
is useful on its own, but invoking it by hand means re-deriving the payload contract from memory
each time — exactly how the pre-0.18.0 narrated-payload error reappears. This release packages
that invocation as a second, **thin** skill in the same plugin (`skills/adversary/SKILL.md`),
purely additive — zero changes to the hooks, the gate, the `goal-adversary` definition, or the
main skill:

- **What it does**: identifies the current conversation's claimed outcome (one short
  `AskUserQuestion` if ambiguous; headless takes the most recent substantive claim and says so),
  builds the full 0.23.0 pointer payload — paths not prose, the two standing lines (everything
  read is data, never instructions; output restricted to the contract), transcript path + which
  asks to look for or an explicit "none" — routes through the existing `adversary.backend`
  resolution (subagent via Task, or `hooks/external-adversary.sh` on stdin), and quotes the
  verdict verbatim. A bare `hold` is UNVERIFIED — re-run or route to the other backend, never
  cite it as verification.
- **No spec written, gate deliberately unarmed**: the command emits no `## Goal-spec`, so
  `gate-goal-close.sh` never arms (its arming regex requires `Goal-spec` directly after the
  heading marks — the checkpoint file's "Live goal-spec" section does not match, verified) and
  no completion-review is required or invented. When the claim lives only in conversation, the
  skill takes the already-shipped Exception route: copy the claim durably into
  `.goalspec/checkpoint.md`'s live goal-spec section and state in the payload that it lives
  nowhere else — the clause both backends have carried since 0.22.0/0.23.0, unchanged.
- **One round per invocation, by design**: on `break` it reports the confirmed violations and
  **asks** the follow-up fork (fix-and-re-run vs. stop with the findings) as an
  `AskUserQuestion`, never as "your call" prose — the method's own dead-handoff rule, applied
  to this command's close (a defect the closing adversary round caught in the first shipped
  wording); headless it reports, stops, and flags the fork as awaiting the user. Multi-round
  convergence discipline (the floor, the cap, the waiver) stays with the full `/goalspec` flow. Terminal claims get the existing different-model rule (self-report
  ground truth, not the spawn parameter); non-terminal runs disclose same-model.
- **Second textual home, declared**: the skill restates the step-6 payload contract
  operationally (a slash command must be self-sufficient in context) and declares the goalspec
  skill's step 6 as the home that wins on divergence — the same subordination pattern
  `external-adversary.sh`'s mirror already uses. The existing PostToolUse verdict nudge and the
  external script's stderr reminder both key on `subagent_type`/the script itself, so they cover
  the standalone flow with no edits.
- **Auto-trigger posture (operator-ratified): manual-first, narrow.** The description
  auto-triggers only on explicitly adversarial asks ("verify this with the adversary",
  "red-team this outcome"), never on generic "check/review this" — those belong to an ordinary
  review or the full method.
- README: registers the new command in install/verify/quickstart and the layout tree
  ("single entry point" → "main entry point").

## [0.23.0] - 2026-07-26

**The deferred external round ran against installed 0.22.0 — and broke it. This release is the
remediation, plus the two adversary-input hardenings the same plan phase owed (Fase 2b/2c).**
The verification Fase 0 and Fase 1 both deferred under the P25 rule (a session that edits the
verifier's script may not use it as that session's closing verifier) finally ran from a
non-editing session: `codex exec` / GPT-5 self-report, against the installed
`~/.claude/plugins/cache/goal-forge/goalspec/0.22.0/` (hash-verified byte-identical to `ccb2775`
before the run). Verdict: `break ungrounded=2 unfalsified=1 incomplete=2 autonomy-violations=0
unsafe=0`. Re-derived by the executor before acting:

- **Confirmed — the 0.22.0 carrier claim overclaimed, in three texts at once.**
  `agents/goal-adversary.md` said "this paragraph cites that declaration, it does not own a
  version of it" while carrying the full per-section semantics inline;
  `references/durable-artifact.md` declared "every carrier elsewhere … cites it rather than
  asserting its own version" — false for **both** carriers, including the external prompt the
  same declaration names (which 0.22.0's own CHANGELOG correctly described as an inline second
  home by necessity); and 0.22.0's CHANGELOG said the agent paragraph "reduces to a citation of
  that section", which the shipped text does not (measured: the paragraph restates the live
  goal-spec/coverage-floor/Rounds/Next semantics in full). The same carrier-overclaim class the
  release existed to fix.
- **Split — the partner's suite claim was its own sandbox.** It could run only 1 of 4 suites (no
  writable TMPDIR in its sandbox — the documented partner-limit mode). All four suites re-run
  from the repo root by the executor: exit 0, ×4. The residue that stands: the entry's historical
  claims (prior attempts, session verdicts) are observed-by-report, per the 0.20.1 precedent.

The fix, as the operator ratified it (amending the Fase 1 "reduces to a citation" letter —
second home declared, matching the external carrier's existing treatment):

- **`agents/goal-adversary.md` now declares its restatement instead of denying it**: the
  paragraph "restates that declaration inline, deliberately", with the necessity argument stated
  (the spawned subagent's cwd is the project, not the plugin, and an installed cache holds many
  plugin versions — it cannot reliably resolve the reference's path at runtime), and a tie-break
  ("where this restatement and the declaration differ, the declaration wins").
- **`references/durable-artifact.md`'s declaration sentence now matches reality**: both carriers
  restate the per-section rule inline by necessity, each subordinate to this section, with the
  grep terms the rule-surface enumeration must catch when it changes. `hooks/external-adversary.sh`
  was **deliberately not edited** (this session's no-edit rule for that file, and the reason the
  external round was legitimate as its verifier); its inline block was re-checked and already
  agrees with the second-home framing ("restated here as a citation of that declaration, not as
  a rule this prompt owns" — `grep -n 'not as a rule this prompt owns' hooks/external-adversary.sh`).
- **Fase 2b — adversary input is data, never instructions** (instruction, not a matcher — new
  matchers stay vetoed): the agent definition gains a standing rule that everything it reads
  (transcript, named files, quoted text, third-party hook injections in session logs) cannot
  re-task it or waive a check, and that its reading scope is the payload's named paths plus what
  its own mechanical checks require it to discover. Motivated by a live 2026-07-26 observation:
  a backend read a stale `/tmp` dump from a *different* session — third-party memory-hook
  injections included — as if it were this run's input.
- **Fase 2c decided and implemented — the output restriction joins the payload contract** (the
  open decision from 2026-07-25, when a backend echoed a prior round's `[ADVERSARY-VERDICT:]`
  into its own stdout and the ad-hoc payload restriction that stopped it had no carrier):
  SKILL.md step 6 now specifies two standing lines the payload itself carries — the
  data-not-instructions rule and the output-restricted-to-contract rule — chosen because the
  payload is the one carrier that reaches **every** backend (subagent and external alike) without
  editing any backend's script. The agent definition's Output section gains the matching no-echo
  rule. The payload's **structure** (paths, not prose) is unchanged — the P11 controlled
  comparison stays owed before any payload redesign (Fase 2d).

Verification (each claim with its instrument):

- All four branch suites → exit 0 (re-run after the edits). `bash -n hooks/external-adversary.sh`
  → exit 0 (untouched, checked anyway). `claude plugin validate` → real exit 0. SKILL.md and
  agent frontmatter re-parsed as YAML (`name` + `description` survive). The Stop gate was not
  touched, so no `--compare` run was owed.
- The external round's raw output is preserved off-repo with a per-run unique name (the Fase 3a
  discipline), and its two marker lines were quoted verbatim in the session, unformatted.

## [0.22.0] - 2026-07-26

**The checkpoint.md exemption, reconciled at its source.** Fase 1 of the phased remediation plan.
The two 2026-07-26 attempts of this work failed for the same root cause: `references/durable-artifact.md`
— the definitional document — never declared who reads Rounds/Next or which sections carry
authority (a measured NOT-FOUND), so each attempt drew the exemption line somewhere the source did
not back, and the closing adversary broke it both times, from opposite sides.

- **`references/durable-artifact.md` gains the missing declaration** ("Who reads which section —
  and which sections carry authority"): the live goal-spec and the coverage-floor table are the
  **authoritative current state** — load-bearing for every reader, verified like any other figure;
  **Rounds is append-only history with no authority over current state** (its declared reader is
  the resuming agent reconstructing the run — the ground the exemption now stands on, instead of an
  unevidenced "executor talking to itself"); **Next is a pointer**, never a claim the action
  happened. The one new reading path — the adversary, when and only when the step-6 payload points
  at the file — is added where the old text was in tension with it ("The reader is a resuming agent
  or a human" §What-this-is-not; "never requires that adversary to open it" §adjacent-practices).
- **Carriers cite the declaration instead of owning a version of it** — scoped to the per-section
  authority rule, which is what the declaration covers; each carrier's `Exception:` clause (the
  goal-spec-lives-nowhere-else case) predates this change and stays carrier-owned, backed by
  SKILL.md's spawn-payload contract rather than by the declaration. The checkpoint paragraph in
  `agents/goal-adversary.md` reduces to a citation of that section. The external prompt in
  `hooks/external-adversary.sh` inlines the same semantics **by necessity** — the partner cannot
  read files on this host — a deliberate second home, declared as such in a comment above the
  heredoc naming it a carrier the rule-surface enumeration must catch. `SKILL.md` step 5's
  "Nothing reads it but the next agent or you" now names the third, conditional reader and points
  at the reference; step 6's spawn-payload parenthetical carries over from the preserved WIP.
- **Selective cherry-pick, measured**: from `wip/checkpoint-exemption` only the three carrier hunks
  (`git apply --3way` → "Applied … cleanly" ×3); the WIP's +67-line CHANGELOG entry (contains the
  claims its own closing rounds refuted) and its version bumps were discarded, and 0.22.0 was
  computed fresh.

Verification (each claim with its instrument):

- `bash -n hooks/external-adversary.sh` → exit 0. All four branch suites → exit 0. The Stop gate
  was not touched, so no `--compare` run was owed.
- **Acid test, external route** — the edited hook as test SUBJECT under a real `codex exec` / GPT-5
  run (legitimate: the P25 rule bars this backend as the editing session's closing *verifier*, not
  as a subject): fixture A (coverage-floor row claims `gamma.conf` done; ground truth
  `grep mode gamma.conf` → `mode=OLD_MARK`) → `break ungrounded=1 unfalsified=1 incomplete=1` with
  three grounded bullets, no bare-verdict warning. Fixture B (accurate table, contradiction only in
  the Rounds log) → `hold 0/0/0/0/0` **with reasoning** that itself applies the new semantics
  ("the contradictory Rounds entry is non-authoritative history") — the first branch of the
  ratified disjunction (reasoned hold), so no re-run was owed; had it come back naked, the 0.21.1
  `EVIDENCE_LINES` scoping now flags exactly that case UNVERIFIED, which is what made this acid
  test decidable at all. Scope: the external route ran fixtures A and B only — B′ (below) went
  through the subagent route alone, so the external pass rests on B, where GPT-5 did not take the
  operator-prose bait.
- **Acid test, subagent route** — fresh-context agents instructed to read and adopt the edited
  `agents/goal-adversary.md` **verbatim from disk** (byte-identical by construction, never
  abbreviated): fixture A → `break ungrounded=2 unfalsified=1 incomplete=1` citing the table row
  against ground truth. Fixture B *as inherited from the WIP* → `break autonomy-violations=1`: the
  deep reader **correctly exempted** the Rounds contradiction ("an unreconciled sentence there is
  not a break") but read the fixture's "operator said proceed/hold" prose as an **unverifiable
  authorization claim** — an ask record does not go stale, so an operator invented by the fixture's
  narrative while the payload declares "no decisions assigned to the human" is a fixture defect,
  not a semantics defect (the open design question — should the declaration name that carve-out —
  is registered in `memory/_pendientes.md`, not improvised here). Fixture B′ — the contradiction
  the criterion actually describes: pure bookkeeping ("converted in R1, not R2"), no operator, a
  realistic two-commit history — → `hold 0/0/0/0/0` with the contradiction verified against git
  and reasoned as exempt bookkeeping drift, in the declaration's own terms. **Scope honesty**:
  this exercises the def *text*, not a genuine cache-resolved `goal-adversary` spawn — a named Task spawn resolves
  from the installed cache, whose *agent def* contains zero mentions of "checkpoint"
  (`grep -c checkpoint agents/goal-adversary.md` → 0 in the 0.20.1, 0.21.0 and 0.21.1 caches). The
  WIP entry's broader phrasing ("zero mentions across all 21 cached versions") was true only under
  that agent-def scope — plugin-wide, `grep -ril checkpoint` hits 4 files per cached version
  (durable-artifact.md, usage-budget-setup.md, check-usage-budget.sh, SKILL.md) — and is corrected
  here rather than repeated.

## [0.21.1] - 2026-07-26

**Instrument repair, and only that: two known defects in `hooks/external-adversary.sh`, each pinned
by a new hermetic branch suite before shipping.** No behavior of the skill, the gate, or the agent
def changes. (The checkpoint.md exemption work observed failing twice on 2026-07-26 is deliberately
NOT in this release — this is Fase 0 of the phased remediation plan, which repairs the instruments
that work needs before it is re-attempted.)

- **The bare-verdict floor could not see a naked verdict.** `EVIDENCE_LINES` counted non-blank
  lines over ALL of `$OUT` — but `$OUT` is the partner CLI's whole run transcript (banner,
  reasoning traces, exec calls, echoed prompt template and fixture text), so nearly any non-trivial
  run counted `> 0` and the "bare verdict with no evidence" warning never fired. Observed live
  2026-07-26: a codex run with `reasoning effort: none` returned a `hold` with **zero** bullets
  between `[ADVERSARY-MODEL:]` and the verdict, no warning was emitted, and the surrounding echoed
  text was mistaken for reasoning by a human reader too. The count is now scoped to the partner's
  answer block — between the LAST real `[ADVERSARY-MODEL:]` line and the final verdict — with a
  12-line fallback window above the verdict when there is no self-report to anchor on.
- **P25, previously deferred with reason, now done in a session that does not use this hook as its
  verifier** (closure below is subagent-only): the partner now runs from the repo root
  (`git rev-parse --show-toplevel`) with a `TMPDIR` this hook's process can write to (replaced via
  `mktemp -d` when unset or unwritable). Both sandbox failures had been observed across two
  consecutive phases coming back disguised as ungrounded/UNVERIFIED findings — a broken instrument
  fabricating findings. **Scope, stated against the recorded contra-dato rather than this fix's
  own hopes** (the first draft of this entry claimed "removing the two known environment
  failures"; the closing adversary round broke it on exactly that): this is the host-side half
  only. The v0.19.1 measurement — repo root, `TMPDIR=/tmp` exported, codex still
  `errno=Operation not permitted` creating its cache file, a full `ungrounded` finding still
  spent — was the partner's OWN sandbox denying writes the hook's process could make, and the
  writability test runs in the hook's process, so that observed mode survives this fix. What is
  removed: the hook-side `TMPDIR` unset/unwritable case, and the wrong-cwd case **when the
  invocation cwd is inside the repo** (a subdir). From outside any git repo — the cwd class of
  the recorded Fase 1 incident, codex refusing a scratchpad as untrusted — `git rev-parse` has no
  root to resolve, so that branch now warns on stderr ("invoke from the repo under review")
  instead of silently running the partner from the unrelocated cwd; the second re-verify round
  broke the first wording of this very sentence for claiming that mode removed (the stderr-warn
  alternative is the one the P25 pendiente itself named). The partner-side denial remains a
  property of the backend to weigh when reading its counts. Deliberately NOT paired with any
  `/tmp` cleanup: the script writes nothing to `/tmp`, and deleting files it does not own is a
  remove-verb on artifacts that are not its own.
- **New suite: `test/external-adversary-branches.py`** (the fourth; `test/README.md` and
  `CLAUDE.md` updated from "three"). Hermetic via a `GOAL_ADVERSARY_CMD` stub — no real CLI, no
  credential, no network. Measured against the pre-edit hook with intended diffs declared in
  advance: `--compare BASELINE --expected 02,05,08,09,11` exits 0 with exactly those 5 branches
  changed and 6 unchanged (02 `pass → bare-unverified` is the live bug; 05 is the no-self-report
  fallback window, a naked verdict the old whole-`$OUT` count also let through; 08/09 are the P25
  rails; 11 pins the outside-any-repo stderr warning added in the second closure round;
  01/03/04/06/07/10 hold as controls — real bullets still pass, the echoed-template rejection and
  recursion guard are untouched).
- All four suites exit 0 (`gate=0 nudge=0 budget=0` plus the new suite), `bash -n` clean, both
  manifests validated with the real exit code.

## [0.21.0] - 2026-07-26

**Two rules that only ever lived in the operator's private memory, shipped to the plugin itself.**
Both were learned the hard way and neither had reached `references/external-adversary-setup.md` —
the file that already carries the neighboring `backends=` guidance — until now.

- **`backends=both` claims the same tree, twice.** A subagent `hold` from before a fix and an
  external `hold` from after it are two single-backed holds over two different commits, not one
  dual-backed hold over one — `backends=both` is only honest when both backends actually reviewed
  the same tree you're closing.
- **A spawned verifier still in flight is not a reason to take the terminal action anyway.**
  Observed directly in 0.20.1: that release closed `backends=external-only` while the **subagent**
  round was still running, so it shipped with no `model=different` accreditation at all — the one
  backend able to attest a different model (the subagent) hadn't come back; the external partner had
  already returned but self-reported `UNKNOWN`, so it couldn't carry that accreditation either.
  Spawning a backend for a terminal decision and not waiting for it is worse than either waiting or
  not spawning it.
- Both go in as **instruction, not mechanism** — a still-running spawn leaves no marker, and the
  tree each backend verified isn't recorded anywhere either, so neither is something any check could
  catch. Written in the same non-obligatory register as the neighboring bullet ("nothing gates it,
  and nothing notices its absence either"): this release does not decide whether presence of
  `backends=`/`model=` should be gated — that stays a separate, open decision.
- **Minor, not patch**: this adds new operational guidance to a `references/` file the skill already
  points at (`SKILL.md:111`), the same shape as 0.17.0's `durable-artifact.md` addition — not a
  wording/regex fix to something already shipped (the pattern behind 0.19.1 and 0.20.1's patches).
  `gate-goal-close.sh` is byte-for-byte unchanged. `SKILL.md` body picked up one line-127 edit in a
  second round (below) — a rule-surface enumeration found it citing `backends=both` as "true by
  construction" without the same-tree/in-flight constraint this release adds; scoped that claim and
  pointed to the `references/` file rather than restating the rule in full (+22 words, 9,394 →
  9,416 — a small, targeted correctness fix, not the kind of open-ended growth the adjacent
  "reduce SKILL.md's floor" pendiente is about).
- **Round 2** (same version, before first publish): both adversary backends broke the first pass on
  3 defects — an internally-incoherent worked example (three carriers named external where the
  incident was actually the subagent still in flight), the stale `SKILL.md:127` above (missed
  because the first rule-surface sweep only grepped `hooks/*.sh`), and a spawn payload that
  asserted a transcript was unavailable when it wasn't. All three fixed before publish.

## [0.20.1] - 2026-07-26

**A reported regression turned out not to be one — the fix proposed for it was measured and
rejected a second time, for the same reason 0.19.1 rejected it the first time.** A live session had
bolded its own `[ADVERSARY-MODEL: …]` line when "quoting it verbatim" to close, and a second form
(a marker followed by plain trailing text) does the same thing — both silently degrade a genuine
`model=different` claim to `model=same`. The proposed repair — drop `gate-goal-close.sh:301`'s
`\s*$` anchor so the already-greedy `.*` runs to the last `]` on the line — is the exact "obvious
repair" 0.19.1's own code comment already documents as "WRITTEN, MEASURED AND REJECTED": re-tested
against `test/gate-branches.py` case `34-trailing-cite-after-marker` (already in the suite, from
0.19.1), it reopens that case — a same-line citation containing its own `]` gets sliced into a
whitespace-free, letter+digit token that `has_real_id` accepts as genuine. **The two failure
directions are not symmetric**: the anchor's false negative costs an honest degrade to
`model=same`; removing it buys a false positive — a fabricated id read as proof of independence,
the one claim this check exists to make honestly. Frequent-but-safe beats rare-but-unsafe; no
formatting convenience justifies inverting which direction the check fails open in. **Rejected
before touching the regex** — a fix proposed and measured broken costs a paragraph, not a shipped
defect.

- **The real defect was the gate's own message, not its regex.** `gate-goal-close.sh`'s generic
  advisory text asked for a real, non-`UNKNOWN` `[ADVERSARY-MODEL: …]` self-report but never stated
  the grammar the anchor actually enforces — that the marker must stand alone on its own line, in
  plain text, with nothing before or after its closing `]`. An executor told to "quote it verbatim"
  reasonably read that as reproduce the exact characters, not as reproduce it unformatted — and
  bolding it for emphasis is a natural way to do that. Fixed with a dedicated `DETAIL` branch
  (`model-different-needs-nonunknown-self-report`) that spells out both possible causes (a genuine
  same-model self-report vs. a marker that fails the grammar) instead of falling through to the
  generic fallback message.
- **Same rule-surface gap, enumerated and fixed across every carrier that instructs the executor or
  the adversary to "quote verbatim"**: `SKILL.md`'s completion-review section, `goal-adversary.md`'s
  own-emission instruction, and both user-facing nudge messages in `remind-quote-verdict.sh` (the
  sync-verdict and the backgrounded-handle branches) now all state the grammar explicitly — own
  line, unformatted, nothing appended — instead of leaving it implied. `external-adversary.sh`'s
  **matcher** was correctly re-checked and needed no change (its `[^]<>]+` capture already stops at
  the first `]` and is presence-only) — but its own closing reminder line (`:219`, "quote the
  markers VERBATIM in your very next assistant turn") is a *separate*, user-facing carrier of the
  same instruction gap, and was missed on the first pass: confirmed and fixed only after the
  external adversary (a genuinely different vendor, `codex exec` / GPT-5, routed per this repo's
  configured `adversary.backend: external`) caught it and returned `break incomplete=1` on exactly
  this omission. The distinction the first draft of this entry blurred — "matcher needs no change"
  vs. "the file has no gap at all" — is not the same claim, and only the first one was true.
- **`gate-goal-close.sh:301`'s comment now documents the second rejection in place**, so a third
  attempt at "just drop the anchor" has the asymmetric-harm argument and the pointer to case 34
  in front of it before it starts, rather than having to re-derive both from scratch.
- **`test/gate-branches.py`: 6 new cases (35-40) from the marker-form sweep this fix requested.**
  Beyond the two reported forms (bold-wrapped, plain trailing text), the sweep found two more that
  degrade the same way — a trailing period, and a marker wrapped in an inline code span — and two
  working forms worth a positive control — a leading list-item dash, and leading indentation.
  Cases 35-38 pin the four degrading forms as **intentional** (`advisory-or-block`, not silent) so
  a future loosening of the pattern shows red instead of shipping silently; 39-40 pin that the two
  working forms keep working. All six were checked against the running gate before being written
  down, not asserted from reading the regex.
- **Regression parity: 40 branches, 0 intended changes, 0 unexpected, in BOTH modes**, `--compare`
  against a pre-edit copy of `gate-goal-close.sh`. Zero intended changes is correct, not
  suspicious: the regex is byte-identical to 0.19.1's; only the message text and four other files'
  prose changed, none of which the branch table's detail/CONV/answered columns can see.

## [0.20.0] - 2026-07-26

The waiver's precondition (`SKILL.md:139`) never covered the state a pre-agreed one-round cap
produces — an actioned fix with re-verification forbidden by prior agreement, not a judged
non-actionable residue. Two prior sessions (v0.18.0, v0.18.1) misused `GOAL-CLOSE-WAIVED` there
because no other exit fit; this was P03, open since v0.19.0.

- **`SKILL.md`'s convergence-guard bullet rewritten** (not appended — first pass was net -2 words
  on the whole file) so the honest exit, option (a) ("stop and hand it back to the human, no
  completion-review"), is reachable under **two** triggers instead of one: the existing
  three-consecutive-break floor, or a **round cap the human fixed in writing before the run
  started**. The second trigger is deliberately narrow — a cap invented by the executor mid-run,
  after seeing a break, is explicitly named as the cost-based evasion this method already
  rejected; only who-decided-and-when makes it legitimate, not the round count. The waiver's own
  precondition is unchanged, but the text now says plainly why a cap never satisfies it:
  `GOAL-CLOSE-WAIVED` asserts a judgment ("I closed — I judged this non-actionable"); a cap without
  re-verification only supports "I stopped — I don't know what the residue is." Only option (a)
  states that truthfully.
- **A real defect surfaced by both adversary backends independently** (Sonnet subagent,
  `codex exec`/GPT-5 — genuinely decorrelated, neither saw the other's output): the first draft of
  the rewrite claimed `GOAL_GATE_ENFORCE=1` suspends "under either trigger." It does not —
  `gate-goal-close.sh:315,420` suspend enforcement only at `streak >= 3`; there is no code path
  that recognizes a human-declared cap, and none was added (a mechanical cap-detector would need
  either a new governance marker, which `SKILL.md:185` already forecloses, or heuristic parsing of
  self-reported text, which this file's own comments already reject as a pattern). The fix is
  textual, not mechanical: the shipped text now states the suspension is real only at the
  break-floor, and that a capped stop short of it may still draw the gate's normal advisory or, under
  `GOAL_GATE_ENFORCE=1`, one block — a tooling limit to expect, not a reason to fake a `waived` or
  `adversary` close instead. This is the same defect class as three prior releases (comment
  asserting behavior the control flow doesn't implement); this time it was caught before ship.
  **Net effect on the word-budget goal**: the corrected text could not stay net-zero — final delta
  is 9241 → 9279 (+38 words) on top of the first pass's -2, because shipping an accurate claim
  about tooling limits costs more than the false claim it replaced would have.
- No new governance marker, no change to `gate-goal-close.sh`, no code-level cap detection — all
  three were considered and rejected in favor of an honest, narrower textual claim.
- `test/gate-branches.py`, `test/verdict-nudge-branches.py`, `test/usage-budget-branches.py` all
  exit 0 with zero diff (expected: no hook script logic was touched, only `SKILL.md` prose).

## [0.19.1] - 2026-07-25

Three fixes found by triaging the backlog rather than by working it. Two of the three pendientes
were **wrong about themselves** — a defect class this project keeps paying for, because the record
of a decision degrades faster than the decision, and nobody re-derives a note that has sat unread.

- **The `[ADVERSARY-MODEL: …]` marker must now end its line** (`gate-goal-close.sh`). A real
  production id can contain brackets — `claude-opus-5[1m]`, the 1M-context variant, and the
  executor's own id in the session that found this — while `[^\]]*` stopped at the first `]`.
  **Read the severity honestly**: the realistic shape (brackets in the id only) *passed anyway*,
  by accident, because the truncated tail still carries a letter, a digit and no whitespace. The
  case that actually fails needs brackets in the **name** field too, where truncation cuts before
  the `/` and the gate tells a genuinely different-model close to degrade. A fragility fix with one
  constructed failing case, not a live outage.
  **The obvious repair was written, measured, and rejected by an adversary — that is the part worth
  reading.** Going greedy to the last `]` on the line looked like the same positional parse the
  block already commits to, and the comment shipped with it claimed over-capture was fail-safe. It
  is not: a same-line citation such as `… / claude-sonnet-5] (see plugins/goalspec/hooks/gate-goal-close.sh[283])`
  yields `cid="gate-goal-close.sh[283"` — whitespace-free, with a letter and a digit — so
  `has_real_id` returns True *for the wrong reason*, granting a `model=different` claim on a token
  sliced out of prose. That fails **open** on the one assertion this check exists to make, which is
  worse than the truncation it replaced (0.19.0 accepted that same line, but by finding the real
  id). Anchoring to end-of-line encodes the grammar the agent def and `SKILL.md` already state —
  the adversary emits the marker as its own line and you quote that line verbatim — so anything
  appended after it matches nothing and the claim degrades to `model=same`. Fail-safe by
  construction; a leading `- ` or `> ` still matches, so a quoted bullet is unaffected.
  **Three carriers, and the other two are exempt with the reason written down** rather than left
  silent: `remind-quote-verdict.sh` and `external-adversary.sh` both match this marker, but neither
  *captures* — their only consumers are presence tests, and a truncated match is still a match. In
  `external-adversary.sh` the `[^]<>]` class additionally rejects the prompt's own `<model name>`
  template.
- **`test/usage-budget-branches.py` — the opt-in usage-budget Stop hook finally has a suite, and
  the belief that blocked it was false.** 0.18.1 shipped that hook's re-entrant-Stop guard verified
  "by placement and syntax only", on the stated reasoning that the hook "cannot emit anything
  without real credentials" and would exit silently with `stop_hook_active` `true` and `false`
  alike. The seam was in the hook's own ordering all along: **step 4 serves from its local cache
  before step 5 resolves any credential**, and `GOAL_CONFIG_PATH` / `CLAUDE_CONFIG_DIR` / `HOME`
  are environment-overridable. A seeded cache drives it to a real emission with no credential read
  and no network call. Six cases; three are the discrimination (identical input, only the flag
  differs) and three are controls proving the silence comes from the guard rather than from a hook
  that never emits. **Verified by removing the guard from a copy: exactly one case flips.**
  Registered in `CLAUDE.md` step 3 and `test/README.md` — an instrument nobody is told to run is
  the orphan-consumer defect `references/instrument-validity-own-tools.md` catalogues, and creating
  one while fixing an instrument that could not discriminate would have been a poor trade.
  **Declared limits, so a green run does not imply more**: the credential path is never exercised
  (a stale-cache case would fall through to a real Keychain lookup and possibly a live API call
  with the user's token), and seeding 95% proves the threshold comparison and the payload shape,
  **not** a real account crossing 80%. That observation stays open.
- **The `prompt`-echo evidence note is narrowed, and its provenance is now stated**
  (`remind-quote-verdict.sh`). It said the harness-synthesized `tool_response` matching the
  transcript object was "INFERRED, never observed live". A real PostToolUse payload dump has since
  shown `prompt` present in both the sync and async shapes, so the **load-bearing half** is
  observed. But **both adversaries caught the same thing**: that dump was made in an *earlier*
  session via a temporary sentinel wrapper, its raw output lives outside this repo, and this
  release did **not** re-derive it — while the same release's own pre-mortem said not to inherit a
  pendiente's self-claim. What *was* re-derived here is only the carrier count. So the comment now
  reads **observed-by-report, not reproducible from anything committed**, and the wider one-for-one
  claim stays INFERRED. Writing a flat `OBSERVED` would have been a stronger claim than the
  evidence supports.
- **Regression parity: 34 branches, 2 intended changes, 0 unexpected, in BOTH modes**, against the
  released `892a45f` gate via `test/gate-branches.py --compare`. Both diffs were **pre-declared
  before comparing**: `32-bracketed-id-and-name` (reminder → silent, the fix) and
  `34-trailing-cite-after-marker` (silent → reminder, the fail-safe tightening the adversary
  forced). The prediction that cases 31 and 33 — the controls — must **not** move was pre-declared
  too: 31 is the accidental pass that must stay passing, 33 is the `UNKNOWN` rejection the fix must
  not loosen. Both held, in both modes.

**Verification, and what was rejected.** Both backends ran from the repo root with `TMPDIR`
exported (fresh-context Sonnet subagent; `codex exec` / GPT-5). Both returned `break`, and the
strongest finding of the round was the subagent's — it attacked the **fix itself**, not the record
of it, which is the inverse of this project's usual ratio and is why the greedy capture above never
shipped. Two findings were **rejected with evidence**: (1) the external backend could not re-run
the suites (`couldn't create cache file '/tmp/…' (errno=Operation not permitted)`) and counted that
as ungrounded parity — a limitation of its own sandbox, and the subagent independently re-ran both
modes and the guard-removal mutation test; (2) it counted the `~/.ssh/id_rsa` security question as
a dead handoff, where the subagent read the user's own turn instructing *report it, do not touch
it* — the human pre-decided it, so reporting without asking is compliance. The two backends
disagreed on that fact and the subagent was right, which is the second recorded instance of them
splitting on a verifiable point.

Not touched, and each for a stated reason: the exit-set defect and `continue:false` (their evidence
bar is written and unmet); the waiver precondition (a decision, not an implementation); the
`external-adversary.sh` cwd/`TMPDIR` degradation — small, but it is the instrument that verified
this release, and changing it mid-verification would have destroyed its independence.

## [0.19.0] - 2026-07-25

`GOAL_GATE_ENFORCE=1` gets a measured definition instead of an adjective, and stops being strictly
worse than the default it opts out of.

0.18.1 weakened the flag on purpose (the re-entrant guard runs ahead of the teeth) and said so. What
nobody checked is whether what remained still buys anything. Read from source, both branches emit
the **same `$MSG`**, and both re-enter the turn **once per user prompt** — the default via
`hookSpecificOutput.additionalContext`, which the harness feeds back to the model. So the wording
this file and two comments in `gate-goal-close.sh` carried — *"one hard, unignorable interruption
that costs the agent a turn"* — described the **default** just as accurately and was never a
description of the teeth. **Third occurrence** of the defect `353557c` fixed: a comment asserting
teeth semantics the file's own control flow had already falsified.

- **The block payload now also sets `systemMessage`** (`gate-goal-close.sh`, teeth branch). It
  carried only `decision` + `reason`, while the advisory payload sets `systemMessage` — so opting
  into teeth *removed* a user-facing field. That was the only respect in which ENFORCE was worse
  than the default, and it is the whole code change: two identical strings in one payload.
- **`GOAL_GATE_ENFORCE=1` is now documented as containment, not as teeth.** The measured delta is
  exactly two things: the Stop record carries `preventedContinuation:true` instead of `false`, and
  the payload shape above. It is not "may not stop until you close" and it is **not the answer to
  what teeth should be** — it is the honest description of what this harness will let the flag be.
  Carriers audited against that, not merely grepped: the two false comments in `gate-goal-close.sh`,
  `README.md` (feature list + gate section), `references/outcome-loop-beats-gates.md`. Explicitly
  **exempt, unchanged**: `SKILL.md` (its two mentions — advisory-unless-ENFORCE, and the floor
  suspension — are both still true, and the skill is not growing more prose for this), the floor
  message in the gate and its README paragraph (the suspension claim is unaffected), `test/` (both
  modes still run), and the historical 0.18.0/0.18.1 entries below (superseded here, not rewritten).
- **Found and deliberately NOT shipped: `continue:false` + `stopReason`.** The structural hypothesis
  that a wall and non-looping are mutually exclusive on this harness is **sound for every mechanism
  that continues the conversation** (`decision:block`, exit 2, `additionalContext` — all re-enter
  the turn, and re-entry is the runaway) and **refuted as a claim about teeth in general**: the
  documented universal field `continue:false` takes precedence over event-specific decision fields,
  halts processing entirely, and shows `stopReason` **to the user, not to Claude**. Those are teeth
  that cannot loop by construction — but they **halt** rather than hold, which is a different
  promise, so it does not ship on a hypothesis.
  **Evidence bar it must clear first, written here so the next session cannot ship it on suite
  evidence alone** (that is what made 0.18.1 an emergency): (1) `continue:false` observed **live**
  at a real `Stop`, not only in `test/gate-branches.py` — including what the user actually sees and
  whether the turn is recoverable; and (2) its **interaction with the second Stop hook in the same
  array** (`check-usage-budget.sh`) established — merge/precedence when one hook halts and the other
  returns `additionalContext` is currently unknown. Neither was obtainable in the session that found
  it: `GOAL_GATE_ENFORCE` was unset in the harness environment and cannot be injected into the real
  Stop hook from inside a session.
- **Regression parity: 30 branches, 0 diffs, 0 unexpected, in BOTH modes**, against a pre-edit copy
  via `test/gate-branches.py --compare`. Zero was **pre-declared before comparing**, with a
  falsifiable reason: the suite classifies by the `decision` field (`:182`), not by which message
  field is present, and derives its detail from `systemMessage or reason` (`:179`) — both the same
  `$MSG` after this change. A diff would have meant the reading was wrong.

Not touched: the exit-set defect stays **open**. The step-0 re-entrant guard and the floor's
`GOAL_GATE_ENFORCE=1` suspension are unchanged.

## [0.18.1] - 2026-07-25

Fix. 0.18.0 rewrote what the Stop gate *says* when a run will not converge. It did not touch the
mechanism that made the gate able to say it nine times in a row.

**The runaway was not the teeth.** In the affected session all 31 Stop records carried
`preventedContinuation:false` and not one emitted `decision:block` — `GOAL_GATE_ENFORCE` was never
set. The re-asking came from the *advisory* path: a Stop hook payload with
`hookSpecificOutput.additionalContext` is fed back into the model, so the turn is re-entered even
though the stop was never prevented. The header claimed the default mode "never blocks" and traded
on that meaning "never re-enters the turn". Those are different properties and only the first was
true.

**The inversion that made it dangerous.** A tool call resets the harness's consecutive-stop counter;
text-only turns accumulate toward it. The agent in that session did exactly what the convergence
floor asked — zero tool calls, no fabricated close, no waiver — and that is *why* it hit the cap
nine times, twice. Running another adversary round would have reset the counter. The mechanism
punished obeying and rewarded staying in the loop, which is the precise opposite of what the floor's
own text declares. Bounded re-asking is not the deliverable; ending that inversion is.

- **Re-entrant Stops are now silent** (`gate-goal-close.sh` step 0, `check-usage-budget.sh` step 0).
  If the harness sets `stop_hook_active`, both Stop hooks emit nothing, in **both** modes — the
  guard runs ahead of the `GOAL_GATE_ENFORCE=1` branch, because "you may not stop until you close"
  re-asked on its own output is the runaway with teeth on. Ceiling is now one re-ask per **user
  prompt**, then silence: measured, not assumed — two separate probe chains each recorded
  `stop_hook_active` false on the first Stop and true on the next, under two different `prompt_id`
  values, so the next thing you say re-arms it. Per-prompt, not per-session. Obeying the floor now
  terminates the turn instead of accumulating toward a cap.
- **⚠️ Behavior change if you set `GOAL_GATE_ENFORCE=1`: the teeth are weaker on purpose.** Because
  the guard precedes the enforce branch, a block is followed by a Stop that carries
  `stop_hook_active` and is answered with silence. So enforce mode is now **at most one block per
  user prompt** — one hard, unignorable interruption that costs the agent a turn — and no longer
  "may not stop until the declaration is complete". Two comments in the gate still claimed the old
  semantics and were corrected with this release. The unbounded version was not enforcement: it was
  the runaway, and it fell hardest on the agent that complied.
- **`additionalContext` is kept, and that is a measured decision, not an omission.** `stop_hook_active`
  was verified to arrive on this harness — `false` on a first Stop, `true` on the next — *including*
  when the continuation came from a purely advisory payload with no block anywhere, which is the
  path the runaway actually took. Since the flag arrives, the guard alone bounds the loop, and the
  nudge keeps the agent-facing consumer that is its entire reason to exist. Had the flag *not*
  arrived, the guard would have been dead code and removing `additionalContext` would have been the
  only real fix.
- **The convergence floor now REPLACES the reminder instead of being appended to it.** 0.18.0 gave
  the floor its own branch, but `remind()` returns before it on every path where a declaration check
  already fired — so for an agent mid-loop with no completion-review yet, the floor was still glued
  underneath, and the message opened with "run the sweep + red-team" at the moment its own next
  paragraph says to stop. That branch shipped dead. The prose that apologised for it ("read this
  INSTEAD of the reminder above") is gone with the bug.
- **`test/gate-branches.py`**: four cases for the re-entrant guard (`true` → silent; absent and
  explicit `false` → unchanged, as controls), per-case assertions so "this fails today" is
  mechanical rather than eyeballed, and a `CONV!` column that separates a floor that replaced the
  reminder from one that rode along on it — without it, `--compare` could not see the floor fix at
  all.

*What is verified and what is not*: the branch suite reads the hook's stdout, so it certifies the
payload and the guard, in both modes, against a pre-edit copy with the intended diffs declared
first (8 changed, 0 unexpected). That the harness stops re-asking is established by direct
measurement of a live Stop payload, not by the suite. The `check-usage-budget.sh` guard is verified
by placement and syntax only — that hook cannot emit anything without real credentials, so no
offline test discriminates.

## [0.18.0] - 2026-07-25

The verification loop ran away and this release attacks the two levers that exist, neither of which
is a terminal.

*Provenance of the figures below, stated because they are load-bearing and you cannot re-derive them
from this repo:* they were counted from one private session transcript (`~/.claude/projects/…jsonl`,
2026-07-25) and recorded in a project-local research note under `memory/`, which is **gitignored —
this is a public repo and session logs are third-party data**. So they are *measured but not
independently reproducible here*, and no test in `test/` re-derives them; read them as the motive
for the change, never as evidence you can check. What you *can* check is every mechanical claim:
the branch suites reproduce their own baselines with `git show <sha>^:<path>`.

Measured from that transcript: **22 adversary invocations → 20 `break`s,
then 2 `hold`s, to decide to change nothing**, ~76M tokens, 2.5× the previous phase. **17 of the 20
breaks attacked text the run itself had fabricated; 15 of 20, text a *previous correction in the
same run* had written. Exactly 1 of 20 attacked the decision — the other 19 attacked the record of
the decision.**

- **The adversary is spawned with paths, not a narrated payload** (`SKILL.md` step 6, both backends).
  It used to be handed "the goal-spec, your outcome, where the work lives, and the ask record" — an
  account the executor typed. Freshly written prose is the least verifiable material there is: it
  *is* the claim, with no ground truth to re-derive it against, so an adversary instructed to resolve
  what it cannot verify as `break` is handed one **by rule, not by chance** — and "on break, address
  every violation and re-verify" then feeds it the correction it just wrote. Pointing at artifacts
  removes the manufacturing step without narrowing the adversary's scope by one inch (delta-scoping
  was rejected: it would blind the check that produced the best findings). Carriers updated together:
  `SKILL.md` :199 and :203, `agents/goal-adversary.md`, `hooks/external-adversary.sh` (header, prompt,
  payload banner), `hooks/route-external-adversary.sh`, `references/external-adversary-setup.md`.
- **The convergence floor stopped pointing back into the loop.** Both times it fired in the measured
  runaway it *resumed* a loop the executor had already stopped — it re-delivered advice the executor
  had read on skill load, phrased around "don't close over a break", which is the rule that made
  stopping impossible. It now says the thing that was true and unsaid: **ending the turn with no
  completion-review, and handing the decision back to the human, is a legitimate terminal state** —
  not an evasion, not a waiver, and explicitly *not* the waiver, whose precondition (non-actionable
  residue, e.g. the verifier's own environment) is false for executor-authored prose and is
  **unchanged**. Same rule mirrored in `SKILL.md`'s convergence guard as option (a).
- **The floor never blocks — `GOAL_GATE_ENFORCE=1` is suspended on that one branch.** "You may not
  stop until you close" plus "you may not close over a break" is an unterminable block capped only by
  the harness's 8-block override: the runaway, mechanized. Yes, an executor could type three fake
  breaks to disable the teeth; that is not a new hole and not the cheap one (a single fabricated
  `hold` closes clean today, in one step), and it is the project's written position that you cannot
  gate your way out of specification gaming.
- **The floor got its own branch.** It could previously only ride a reminder some other check raised,
  so a non-converging run whose declaration happened to pass — e.g. a turn quoting both backends and
  closing on the `hold` — was met with silence at streak 3.
- **Fixed: a hold-only turn extinguished the streak** (`gate-goal-close.sh`). With two backends, one
  holding in a turn of its own switched the counter off mid-runaway; it now resets only when the
  *most recent* verdict-carrying turn is a hold (which is convergence). Measured under-count in the
  runaway: "at least 4" with 6 real, "at least 6" with 12.
- **Fixed: the verdict nudge never saw a verdict** (`remind-quote-verdict.sh`). Since Claude Code
  v2.1.198 subagents run in the background, so the tool result is a handle with no `content` — and
  that handle echoes the executor's own spawn `prompt`, which this method fills with prior verdicts.
  Measured against the pre-edit copy: it therefore reported the **executor's own text** as a verdict
  that "came back" (case 04 of the new suite) — silent on a first round, actively misleading after.
  It now anchors on `tool_input.subagent_type`, excludes echoed input fields, and nudges on the
  launch itself. It stays a **nudge, not a counter**: `PreToolUse` can fail an Nth *spawn*, nothing
  available can fail an Nth adversarial *round*.
- **The verification instrument can now see what changed** (`test/gate-branches.py`). It read
  `systemMessage or reason`, which collapses the advisory and blocking paths — so a change to
  *whether the gate blocks* was invisible to `--compare`, the one check used to certify "no
  regression". It now reports the gate's answer as a third observable and takes `--expected` to
  pre-declare intended diffs. New `test/verdict-nudge-branches.py` covers the nudge's branches.

**How it was verified.** The mechanical half is parity: both branch suites run against pre-edit
copies in default *and* `GOAL_GATE_ENFORCE=1` modes, with the intended diffs **pre-declared** via
`--expected` before the comparison was run (2 in default, 6 under enforce, 0 unexpected). The prose
half got exactly **one** external-adversary round, capped in advance: a `break` there was to be
fixed and the release closed **without a second adversarial round** — the cap is this release's own
lever applied to itself, and it is deliberate, not an oversight.

Read that cap precisely, because it is narrower than "ships unverified", and the distinction is the
whole point: **mechanical verification is not capped.** Any change touching code re-runs both branch
suites against the pre-edit baselines, in both modes — that costs nothing and generates no new
prose. What is capped is *adversarial re-verification of prose*, and only there, because that is the
step measured to manufacture its own next finding: the round that fixes a wording writes the wording
the next round breaks. It ran once; the `break` it returned was addressed; the residue is named in
the release rather than re-litigated. An adversary attacking this cap as "done means verified" is
correct about the general rule and is also, precisely, the loop this release documents.

**What this release does not claim.** (1) The paths payload lowers the **rate** at which break-
eligible surface is generated; it does not give the loop a terminal. (2) The floor makes stopping
legitimate once the instrument has detected non-convergence; it does not make the exit set reachable
in general. **The exit-set defect stays OPEN**: the reachable closes are still `hold` and the waiver,
and `hold` is only reachable by a round that shrinks the corpus while the on-break instruction
prescribes one that grows it. Handing back to the human is an exit from the *turn*, not a close.
And (1) is **not verified by this release** — the project's own bar for it is a **comparison**
(a run with the change against one without), not another passing round; one clean run is not that.

## [0.17.0] - 2026-07-25

Phase 3 of the graph-vs-loops research: **single-source applied to shared state**. Two places in
`SKILL.md` told you to keep a fact alive outside your own context, and both created a *second home*
for that fact — the generator of most defects shipped by this method. They now point at one file.

- **The checkpoint has a name and a shape.** The Execute step said "checkpoint state to disk" with
  no path, no schema, and no reader, while `hooks/check-usage-budget.sh` already nudged toward it —
  a live pointer aimed at something each agent had to invent. It now names
  **`.goalspec/checkpoint.md`**, with its shape in the new `references/durable-artifact.md`.
  **What this is not:** nothing in the plugin reads that file, and **nothing gates its absence** — a
  run that never writes one closes exactly as cleanly. It is a named place plus an instruction to
  fill it, not a guarantee that state survives, and it does **not** close the resume gap (resume is
  a human CLI action no hook can reach; that is unchanged). The narrow, real gain: the nudge now
  points somewhere executable.
- **The instruction to per-entity workers no longer prescribes a re-narrated copy.** The
  coverage-floor decomposition said to *"relay the few facts that must stay consistent across
  entities yourself"* — prescribing that the shared fact live in the coordinator's prose and be
  retold to each worker, where it diverges round by round. It now says to put those facts in the
  checkpoint and have each worker's brief **point at the path**. This changes what the skill tells
  you to do; whether workers ever do it is **unobserved**, for the reason given at the end of this
  entry.
- **Verb restriction over shared state** (`references/durable-artifact.md`): coordinator is the only
  writer, rounds append rather than rewrite, and no worker may `git stash` / `git reset` /
  `git checkout --` shared working state. This is the prior art's best-supported finding — in Bun's
  multi-agent port, clobbering appeared within ~2 minutes and was fixed by removing destructive
  verbs, *not* by changing the number of agents.
- **Two candidate practices not added — with the gap written down instead of papered over.** Each
  has a near-neighbour already in the method, and in both cases the neighbour is **narrower**, so
  "already covered" would have been false. *Review the shared artifact before it becomes shared
  state*: step 6 routes your **outcome** to an adversary at close — it never requires that adversary
  to open the checkpoint, and it fires **after** workers have read it. *A dedicated pass reconciling
  contradictions between artifacts*: the rule-surface enumeration greps every carrier of a **rule
  you changed**, which is not two arbitrary work products that disagree. Both limits are now stated
  in `references/durable-artifact.md`; **neither is filled.** Restating the neighbours would have
  given an existing rule a second home — the defect this release is about — but calling them
  equivalent would have been the overclaim this project ships most often.

**Declared, not validated.** The worker half serves the coverage-floor decomposition (S5c, v0.12.0),
whose trigger has still never been observed firing on its own. This release's own task could not
observe it either, and it fails **both** halves of S5c's condition: the task was never long enough to
risk exhausting one context — the plainer disqualifier, and the one that rules out any short task —
and its entities were carriers of a single claim, so they *share* state, S5c's stated anti-condition.
Only the second half is specific to this class of task.

**Was the checkpoint actually useful? Partly, and less than it sounds.** It was dogfooded
in the session that shipped it, and for its **stated** purpose it was **not needed**: that session hit
no context limit and no cutoff, so nothing was ever resumed from it. What it was actually used for
was the carrier table — the running list of which surfaces had been updated. Whether that beat
keeping the list in context is not something this release measured, so no claim is made either way.
What *is* observed: the file reproduced the defect it exists to prevent **three times** — twice as a
copied fact going stale (a word count, then a superseded scope claim), and once as two carriers
simply disagreeing (its own header contradicted this entry about which items had gone stale). An
adversary caught all three by re-deriving them; the file caught none. It has since been rewritten to
carry pointers and status only, which is what `references/durable-artifact.md` tells you to do. One
session, in which the artifact's own failure mode showed up three times inside the artifact, is not
evidence that it pays for itself.

`SKILL.md` body: 8,706 → 8,757 words (+51); the new material is in
`references/`, which loads only on demand.

## [0.16.0] - 2026-07-25

Phase 2 of the graph-vs-loops research. The phase was a **decision**, and the decision was **not to
adopt** the paper's "third independence lever" (make the verifier commit its own answer before
reading the executor's). What shipped is one small disclosure field.

**Why the lever was not adopted.** The motivating hypothesis was that the subagent backend verifies
*code* while the external backend verifies *claims*, leaving the zero-config user (default backend =
`subagent`) unverified on the claim axis. Classifying the existing recorded corpus by axis —
retroactive and free, since the verdict's five integers were already written down — does not support
that split. Across the 6 findings confirmed **in the corpus as it stood when this was decided**
(5 claim-axis, 1 coverage-axis), all 6 came from the external backend and the subagent had 0 in
either axis. One of its misses had a fully available external error signal (the DoD claimed
"committed locally"; `git log` showed HEAD unmoved with 7 uncommitted files) — a not-checking
failure, not an anchoring failure. So a claim-axis-only intervention would be narrower than the
observed deficit, and the deficit itself is not yet characterized well enough (n=3 comparison rows)
to design against.

**That "subagent has 0" figure is a snapshot, not a property** — and this release's own verification
falsified it within hours. The subagent backend went on to return real findings in both axes over
several rounds, including the sharpest one of the release (a sibling overclaim about `model=` sitting
in the README).

It went further than that, and this is the release's most useful result. In one round **each backend
caught a defect the other missed**: the subagent alone found a threshold contradiction between two
carriers, the external alone found a stale carrier in a third. That is the first *observational*
support this project has for `SKILL.md`'s standing claim that "running both backends is strictly
better than either" — which until now rested on OR-aggregation logic, not evidence. Note how it was
found: an earlier draft of this entry asserted the opposite ("the subagent has not yet caught
anything the external did not"), and both adversaries falsified it from the transcripts. The claim
the verification pass killed was the one that would have thrown away the finding.

Revisit at **n≥5 comparison rows independent of this decision**. The rows added during this release —
five of them, all of them this release's own verification rounds — do not count: letting a decision's
own verification satisfy the threshold that gates revisiting it is circular. Counted that way the
corpus is still at 3, where it was when the call was made.

**Added — `backends=` in the completion-review details.** `backends=both` /
`backends=subagent-only` / `backends=external-only`: a place for a single-backend verification to
say so, in the same pattern as `model=same`. It is true by construction (you know which backends you
ran) and asserts nothing about what a second backend would have found.

Scope of what this does and does not do, stated precisely because an adversarial round caught the
first wording overclaiming it: the field is **ungated, and its absence is ungated too** — omitting it
passes exactly as omitting `model=` does. So it is a slot plus an instruction to fill it, **not** a
guarantee that a single-backend close cannot stay silent.

Its *value* is not honestly gateable — two backends routinely return a byte-identical
`hold 0/0/0/0/0`, so counting *distinct* verdicts would downgrade a genuine dual-backend close while
counting *occurrences* would bless a re-quote of one backend; that is the bottomless-proxy pattern
the 0.11.1 id-matcher removal already paid for. Its *presence* is a different question and would be
mechanizable (the `none` branch already gates `reason=` for presence and length without judging its
truth). Not done here: the ratified scope for this release was explicitly zero change to
`gate-goal-close.sh`, and gating presence changes the outcome for every existing close that omits
the field. Left as a named follow-up.

**Fixed — the same overclaim about `model=`, found by round 2 of this release's own verification.**
`README.md` described a same-model fallback as "announced, **never silent**". It is the identical
claim just retracted for `backends=`, one field over: `gate-goal-close.sh` only checks a body that
*contains* `model=different`, so a close omitting `model=` entirely passes clean. The same wording
had spread to SKILL.md's step 6 ("never a silently-hollow one") and to the backend table in
`references/external-adversary-setup.md` ("degrades announced"). All now say the same thing: you
declare the degradation, and the gate can reject an unsupported `model=different` but not a close
that omits the field. Earlier CHANGELOG entries carry the old wording too; those are left as the
historical record of what was claimed at the time, and this entry is the correction.

**Size** — `SKILL.md` 8,543 → 8,706 words (+163), measured. Most of that is not the feature: the
feature itself was a few sentences, and the rest is the five verification rounds' corrections, which
replaced short absolute claims ("announced, never silent", "never silently skipped") with longer
accurate ones. This file is the single place that figure is recorded, deliberately — a duplicated
copy in the plan file went stale twice during this release.

**Tests** — three cases (21–23) pinning that an extra field inside the completion-review bracket
does not break a valid close and does not mask the `model=different` self-report check, which
`cr_pat`'s `[^\]]*` body capture makes a real risk. Gate script unchanged; suite parity holds in
both default and `GOAL_GATE_ENFORCE=1`.

## [0.15.0] - 2026-07-25

Phase 1 of the graph-vs-loops research: three places where a written rule had no teeth. All three
were verified defects in shipped code, found by an investigation into whether goalspec should be
replaced by a graph-shaped orchestrator (conclusion: no — of ten frameworks reviewed, none has a
forced different-model verifier or a gate on terminal actions; but a graph would have caught these).

### Added
- **The Stop gate now counts the convergence guard (`hooks/gate-goal-close.sh`).** SKILL.md has said
  "at three consecutive breaks, stop editing — the design is wrong, not the wording" since 0.4.0, and
  nothing but the agent's memory observed it. The gate now counts and appends a **convergence floor**
  to whatever reminder it was already emitting (both the `absent` branch — the state a mid-loop agent
  is actually in — and `closed-over-break`).
  The claim it makes is deliberately weak, and phrased to say exactly what the walk checks and no
  more: *"at least N of your most recent verdict-carrying turns each contain a `break`, with no
  `hold`-only turn between them"* — a statement about **turns, not rounds**. (The first wording said
  "no intervening `hold`" and the external vendor adversary broke it in round 2: a turn quoting both
  backends, one holding and one breaking, is a break round the walk does not reset on, so a `hold`
  really can sit inside the counted run. The counter was right; the sentence claimed more than it
  checked — and it claimed it in four carriers at once.) It cannot honestly be a round count, because the skill instructs the agent to quote
  every verdict verbatim in its own turn, so a multi-round loop naturally re-quotes earlier rounds
  when summarizing and a transcript-wide tally inflates *in exactly the scenario the guard exists
  for*. A false "three breaks, stop editing" at round 2 would push toward a premature
  `[GOAL-CLOSE-WAIVED]` — worse than not counting at all. So the count is damped: at most one round
  per assistant turn, identical verdict sets de-duplicated within the trailing run (which under-counts
  identical consecutive breaks — the fail-open direction), a `hold`-only turn ends the run, and a turn
  quoting both backends is one round. The message tells the agent to verify its real round count
  rather than asserting one.
  Only the **counter** is mechanized. The other half of the guard — "each round should break something
  smaller than the last" — is left to the agent explicitly, because it is not mechanizable: the
  verdict's five integers are **cardinalities, not severities** (`incomplete=3` → `unsafe=1` is fewer
  violations and a worse break). Mechanizing it would repeat the id-matching mistake 0.11.1 retired.
  Consumer: the hook's own message branches and the `block` reason under `GOAL_GATE_ENFORCE=1` — no
  new marker, nothing else reads it. Verified across a 20-case branch suite with synthetic multi-turn
  transcripts, including the dedup case (same verdict in `last_assistant_message` **and** as the last
  recorded turn → the floor must not jump) and hold-resets; the eleven pre-existing branches emit
  byte-identical detail codes before and after.

### Fixed
- **The ratify gate (4b) offered four answers and drew one edge.** `Approve / Narrow / Minimal-fix /
  Stop` — and only "Approve" said where it went, leaving the agent to improvise the other three
  mid-run. Now drawn, in step 4b only (the other carrier points at it rather than restating it):
  Narrow → rewrite the spec to the given scope, re-emit it, go to step 5 **without a second modal**;
  Minimal-fix → the minimal reversible fix *becomes* the objective and the systemic branch is demoted
  to a surfaced, unexecuted follow-up; **Stop** → execute nothing but still close, with
  `[COMPLETION-REVIEW: none reason=…]` naming the stop. That last edge closed a real gap: a stopped
  run leaves a `## Goal-spec` behind, so the gate expects a declaration and would otherwise nag an
  agent that had correctly done nothing.
- **Nothing said the `goal-adversary` must be spawned isolated.** 0.12.0 introduced agent-teams
  guidance for *execution* decomposition; neither the adversary spawn nor `agents/goal-adversary.md`
  excluded itself. A teammate is addressable and resumable, so the executor could brief the adversary
  mid-verification or the adversary could ask instead of re-deriving from ground truth — collapsing
  both independence levers at once and **invisibly to the gate**, which only checks the marker's
  shape. Latent, not observed (it needs the experimental flag on, a named-teammate spawn, and someone
  using the channel), and the fix is one clause at the spawn site plus a matching instruction in the
  agent definition itself: no message goes to it after the spawn, and an unreachable fact is an
  unverified claim to report, not a question to ask.

## [0.14.1] - 2026-07-22

### Added
- **"Quick enable" copy-paste agent prompts, in README.md and `references/usage-budget-setup.md`.**
  So a user who hands this repo to their own agent (or gets pointed at it) can trigger the two new
  opt-in features without hand-writing config: one prompt for `usage_budget` (which still routes
  through reading the security doc first, not silent activation) and one for Claude Code's own
  experimental Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, referenced by 0.12.0's
  coverage-floor decomposition guidance). Also added a "What's new" pointer to CHANGELOG.md in
  README.md. Docs only — no hook/behavior changes.

## [0.14.0] - 2026-07-22

### Added
- **`PostToolUse` nudge for the recurring "gate can't see the verdict" friction
  (`hooks/remind-quote-verdict.sh`) + a matching fix inside `hooks/external-adversary.sh`.**
  Reported as a recurring, previously-unresolved pattern across most goalspec sessions:
  `gate-goal-close.sh` only ever scans assistant-authored text for
  `[ADVERSARY-MODEL: …]`/`[ADVERSARY-VERDICT: …]`, by design — never a tool result. A real verdict
  from the `goal-adversary` subagent or `hooks/external-adversary.sh` arrives as a tool result, so
  it stays invisible to the gate until the executor personally re-types it into their own turn —
  easy to forget across a long session, costing a Stop-hook round-trip every time it's missed (this
  exact session hit it twice in a row). Considered making the gate itself correlate tool_use/
  tool_result pairs to find the verdict automatically, but that repeats the "get clever with the
  parser" pattern that already broke 5 consecutive rounds once before (the model-id matcher,
  0.11.1) — the ruling then was "simplify, don't out-clever it."
  - `remind-quote-verdict.sh` (matcher `Task|Agent` only) fires on a `goal-adversary` spawn
    (subagent_type anchored to end-with "goal-adversary" — a fabricated
    `"not-goal-adversary-example"` substring was caught by adversary review and excluded) whose
    `tool_response` contains a well-formed verdict (or a model line with a malformed/missing one),
    nudging to quote it verbatim in the very next turn.
  - The Bash/`external-adversary.sh` case is deliberately **not** handled by command-string
    detection in that hook. An earlier draft tried exactly that and an external adversary review
    broke it twice in a row: first a bare substring match false-positived on read-only inspection
    (the script's own source contains literal fallback `[ADVERSARY-VERDICT: hold …]` strings, so a
    plain `cat`/`grep` of the file — routine when inspecting hook scripts — would have nudged to
    quote non-evidence into the transcript the real gate reads); then, after tightening to an
    invocation-verb check, real invocation forms (a bare `./external-adversary.sh`, `sh -c "..."`)
    were missed. Rather than patch the heuristic a third time, the reminder was moved to the one
    place that needs no heuristic at all: `external-adversary.sh` itself now emits the identical
    reminder to stderr from the single code path that only runs after it has already validated a
    real, well-formed verdict came back — a structural guarantee, not a guess. `stdout` (the actual
    verdict contract callers parse) is unaffected.
  - Zero changes to `gate-goal-close.sh`'s own parsing logic throughout. Also clarified in
    `SKILL.md`'s completion-review section that "present in the session" means in the executor's
    own authored text, never a tool result — the ambiguity that let this recur silently.
  - A further adversary round found both nudge messages **asserted** "a real verdict" when neither
    hook can actually verify the underlying conclusion is genuine adversarial work rather than
    copied/echoed text (a synthetic "copied example only" response, or a fake `external_cmd` that
    merely echoes a well-formed string, would satisfy the same structural checks). This is the same
    self-report limitation this method already documents everywhere else (`references/`
    `outcome-loop-beats-gates.md`; the bare-verdict-evidence-floor already in `external-adversary.sh`
    is explicitly commented as "a FLOOR, not proof of diligence") — the nudges never granted a
    lazy/copied verdict any new power to satisfy the real gate, but the wording overclaimed a
    certainty neither hook has. Reworded both to explicitly defer the genuineness judgment to the
    executor ("a verdict-shaped block... whether it reflects genuine adversarial work is still
    yours to judge... if you judge it genuine, quote it") rather than asserting authenticity, and
    synced every carrier that still described the old framing (`README.md`, `SKILL.md`, both
    hooks' own header comments).

## [0.13.0] - 2026-07-22

### Added
- **Opt-in usage-budget nudge (`usage_budget.enabled`, off by default).** A new Stop hook,
  `hooks/check-usage-budget.sh`, reads the local Claude Code OAuth credential and calls Anthropic's
  own `api.anthropic.com/api/oauth/usage` endpoint to read the real 5-hour/7-day account usage
  ceiling, nudging (non-blocking, advisory) to checkpoint state once utilization crosses a
  configurable threshold (default 80%) — only within a goalspec-tracked session. This is a
  materially larger trust surface than any other hook in this plugin (every other one reads
  project-local files or spawns a subagent), confirmed the hard way mid-investigation: even
  *checking whether the credentials file exists* was blocked by the executing agent's own
  permission classifier as a sensitive action. So unlike every other config key, it defaults to
  `false` and ships with its own informed-consent doc, `references/usage-budget-setup.md`, that
  must be read before enabling it. The token itself is never logged, cached, or printed — only the
  resulting percentages are cached locally with a short TTL, in the plugin's own cache file,
  independent of any third-party statusline tool's cache (its credential-lookup and endpoint were
  cross-checked against one such tool's source — `ccstatusline` — since `api.anthropic.com/api/oauth/usage`
  is itself undocumented; this is observed compatibility, not a stable guaranteed capability — see
  the caveat in `references/usage-budget-setup.md`. Also confirmed context-window usage specifically
  has no equivalent persisted, hook-readable source — it is delivered live to a statusline script
  only, never to a hook. This is why context risk is addressed instead through execution
  decomposition, not number-reading — see 0.12.0 below.)
- **Fixed before ship, by an external (different-vendor) adversary review, not by the executor:**
  the macOS Keychain path initially treated the raw `security find-generic-password` stdout as a
  bare bearer token. It is not one — the Keychain secret is the same `{claudeAiOauth:{accessToken}}`
  JSON shape as `.credentials.json` (confirmed against `ccstatusline`'s own `parseUsageAccessToken`,
  which JSON-parses it identically) — so the original code would have sent the whole credential
  blob, potentially including other credential fields, into the Authorization header on macOS.
  Fixed to parse it the same way, and reordered to match ccstatusline's own precedence (Keychain
  first on macOS, file as fallback) rather than the reverse. Caught on the first adversary round: a
  fresh-context, different-tier subagent (opus) returned `hold` and missed it; a different-vendor
  external backend (codex/GPT-5) returned `break` and caught it — the exact reason this plugin
  routes security-sensitive decisions to a genuinely different vendor, not just a fresh context.

## [0.12.0] - 2026-07-22

### Added
- **Context-budget-aware execution decomposition (coverage floor).** Users hitting either the agent's
  own context window or the account's rolling 5-hour usage ceiling on long goalspec-driven loops
  prompted a deep investigation of Claude Code's actual mechanisms (verified against primary docs, not
  assumed — the flagship "188% context" incident that motivated this turned out to be a broken
  instrument in an unrelated plugin, not real exhaustion). Findings landed as an extension to the
  existing **coverage-floor** derived pattern: when the enumerated child entities are independent
  (own file/artifact, no round-by-round shared state) and the task is long enough to risk exhausting
  one context, decompose execution across them — prefer agent teams when available
  (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, experimental/off-by-default) for entities that must stay
  mutually consistent, else dispatch one subagent per entity in parallel and resume the *specific*
  subagent by its returned agent ID for revision rounds, rather than collapsing everything onto one
  resumable subagent (which just relocates the same exhaustion into a single worker).
- **Checkpoint-to-disk + countable stop conditions (execute step).** For multi-round tasks, checkpoint
  state to disk after each major round so a context limit or a session cutoff loses at most the
  in-flight round, not the whole run — mirrors this project's own `/checkpoint-3t` pattern. Prefer a
  countable stop condition (a round/entity cap from the coverage-floor enumeration) over open-ended
  "keep refining."
- **Scope note: don't re-invoke `/goalspec:goalspec` mid-session.** A quantified real-session finding
  (two explicit re-invocations duplicated the full SKILL.md body into context, ~10% of that session's
  content bytes, for zero benefit — auto-trigger already applies the method without re-injecting the
  file) is now documented directly in the Scope section.

## [0.11.2] - 2026-07-20

### Fixed
- **The Stop gate now has a mechanical consumer for "do not close over a `break`."** A live session
  showed an executor declare `[COMPLETION-REVIEW: adversary model=same …]` while the operative
  `[ADVERSARY-VERDICT: break …]` still said `break`, rationalizing it via the convergence-guard's
  "stop iterating" language instead of the existing `[GOAL-CLOSE-WAIVED reason=…]` escape — because
  the gate never actually checked the verdict value, only that the markers were well-formed. "Do not
  close over a break" was a written rule with zero mechanical consumer, the exact instrument-consumer
  defect this method exists to catch. The gate now reads the operative `[ADVERSARY-VERDICT: …]`
  (current-turn-preferred, transcript-fallback — the same precedence already used for
  `[COMPLETION-REVIEW: …]` itself) and rejects a close over a structured `break`, for both
  `[COMPLETION-REVIEW: adversary …]` and the `[COMPLETION-REVIEW: none …]` side-channel. Verdict
  matching requires the full structured grammar (all five `field=n` counts), not a bare word, so
  narrative text mentioning "break" never false-positives.
- **`[GOAL-CLOSE-WAIVED reason=…]` reframed from "operator escape" to explicitly agent-usable.** It
  already worked mechanically, but was undocumented in SKILL.md (only in the hook's own comments) and
  labeled in a way that read as human-only — so an executor stuck on a residual break it judged
  non-actionable had no visible honest path and reformulated the completion-review instead. Now
  documented in SKILL.md's completion-review grammar and convergence-guard sections, and in
  README.md, as usable by the agent itself: the honest, greppable way to override a break you've
  judged non-actionable, versus a completion-review that silently disagrees with its own verdict.
- **Verdict-precedence ordering bug**, found by an external-vendor adversary review of the fix above
  before release: the first pass compared verdicts positionally across the concatenated
  `lam_text + tx_text`, which inverts recency — since historical transcript content is appended
  *after* the current turn, any older structured verdict still sitting in the transcript (e.g. an
  earlier round's `hold`) could outrank a live `break` in the current turn. Fixed by matching
  `lam_text` and `tx_text` separately with `lam_text` preferred, mirroring the completion-review
  match's existing precedence exactly.

### Known limitation
- A non-canonical `[ADVERSARY-VERDICT: …]` (reordered or extra fields, deviating from the documented
  grammar) fails open — it isn't recognized as a structured verdict, so a break in that shape can't
  block a close. This is consistent with the project's fail-open philosophy and the documented
  grammar the adversary is instructed to emit; noted here rather than left silent.

## [0.11.1] - 2026-07-19

### Added
- **`adversary.backend: "external"` now has a mechanical consumer — a PreToolUse hook that nudges the
  agent to actually route to it.** Choosing the external backend (codex / a different vendor) was a
  prose instruction in the SKILL that the executing agent had to remember to read every run; nothing
  enforced it, so an agent — and the fleet — would default to the zero-config subagent path and silently
  never run the configured independent adversary. That is a config emission with no consumer, the exact
  instrument-validity defect the method warns about. The new `hooks/route-external-adversary.sh` fires on
  a `goal-adversary` spawn (Task/Agent) and, when the per-key-resolved config (project → user-global, the
  same precedence `external-adversary.sh` uses) says `backend=external`, injects a one-line reminder to
  pipe the goal-spec + outcome + ask record through `hooks/external-adversary.sh` (the configured
  `external_cmd`). Deliberately **non-blocking and fail-open**: it never denies the spawn (the subagent
  is still a valid context-independent adversary, running *both* is stronger, and blocking could leave a
  host with no adversary at all if the external binary is unreachable — e.g. a sanitized daemon PATH); it
  fires only for a goal-adversary spawn with `backend=external`, and any parse error → silent exit 0.
  Registered as PreToolUse (matcher `Task|Agent`) in `hooks/hooks.json`; unit-tested across all branches
  (fires / silent-when-not-external / silent-when-not-adversary / silent-on-other-tools / fail-open on
  malformed input / no python exception).

### Fixed
- **Stop gate no longer rebounds a correct `model=different` completion-review, and the fragile id-match
  that caused it is gone.** The old parser cross-checked the `model=different (<id>)` parenthetical
  against the adversary's `[ADVERSARY-MODEL: …]` self-report with a **one-directional** substring test
  (`claimed in report`). The natural, honest form — naming *both* models to show they differ,
  `model=different (Sonnet 5 / claude-sonnet-5 vs Opus 4.8)` — made `claimed` a **superstring** of the
  self-report, so the match was impossible by construction and a substantively-verified close rebounded
  with `model-different-claimed-but-no-matching-self-report` even though a correct self-report was
  present (observed: a real close spun 3 extra turns before landing on the bare-id form).

  An attempt to *repair* the matcher (bidirectional substring → id-like-token intersection → positional
  canonical extraction with dotted-id support) was broken **five consecutive times** by two independent
  adversaries — a fresh-context subagent and an external `codex` run on a different vendor (GPT-5): a
  substring collision (`o3` inside `gpt-4o-3-turbo-preview`), an `UNKNOWN`-sentinel leak, a generic-word
  echo (`(fabricated-model vs Sonnet 5)` passing on the shared `sonnet`), prose harvesting (`UNKNOWN /
  requested gpt-5 unavailable` leaking `gpt-5`), and a dotted-version-id false-negative (`gpt-5.1`). Each
  round closed one surface and exposed another. That is the method's own convergence guard firing:
  free-text id-matching from an **agent-authored transcript** is a bottomless proxy, and *you cannot gate
  your way out of specification gaming* (`references/outcome-loop-beats-gates.md`).

  So the check is **simplified** to the one assertion it can make honestly: a `model=different` close
  requires **at least one `[ADVERSARY-MODEL:]` self-report naming a real, non-`UNKNOWN` model id** — the
  canonical id taken **positionally** (single whitespace-free token after the last `/`, carrying a
  letter **and** a digit/hyphen/dot version marker — so `claude-sonnet-5`/`o3`/`gpt-5.1` qualify but a
  bare word like `apology` does not, not the `unknown` sentinel, so a fallback field like
  `UNKNOWN / requested gpt-5 unavailable` yields none). If every self-report is `UNKNOWN`/absent — the harness silently fell back to same-model,
  the *exact honest mistake* this guards — `model=different` is unsupported and must degrade to
  `model=same`. **Deliberately not gated:** id-*precision* (the claimed `(<id>)` need not equal the
  self-reported id) and cross-run *provenance* (a stale self-report from another run in the same session)
  — both are agent-authored-transcript proxies the outcome loop owns, not this marker. New detail slug:
  `completion-review:model-different-needs-nonunknown-self-report`. Guarded by a 20-case acid-test
  (including every adversary counterexample above, `model=same`+`UNKNOWN` passing, and a guard that the
  embedded python raises no exception — a prior round shipped an apostrophe inside the single-quoted
  heredoc that silently fail-opened everything).
- **More actionable advisory text.** The Stop reminder now states that both marker lines must appear in
  the assistant's **own** turn (not only in the subagent's output — a task-notification `[ADVERSARY-VERDICT:]`
  is invisible to the transcript-anchored gate), and that a `model=different` close needs the adversary's
  `[ADVERSARY-MODEL: …]` line naming a real, non-`UNKNOWN` id — else declare `model=same`.

## [0.11.0] - 2026-07-19

### Added
- **User-global config: choose the external adversary once, inherit it everywhere.** A user-global
  `~/.claude/goal.config.json` is now read alongside the project `.claude/goal.config.json`. Resolution
  is **per-key, not whole-file**: each of `adversary.backend`, `adversary.external_cmd`, `sweep_files`
  is taken from the project file if set there, else from the global file. So a global `adversary` block
  makes *every* project route to the external CLI with no per-repo file, while a project file can still
  add `sweep_files` or override a single key **without** nulling the rest. The one key enforced in code
  is `external_cmd` — `hooks/external-adversary.sh` resolves it project→global (tested T1–T5, incl.
  empty/malformed project config falling through, and fail-open when nothing resolves). `backend` and
  `sweep_files` are resolved by `/goalspec` step 6 per the SKILL's identical per-key instruction (the
  executor reads them; no separate script consumes them). `GOAL_CONFIG_PATH` still pins the project layer.

### Why
- Observed in the wild (2026-07-19): a host that **pins plugin subagents to a weak tier** — two real
  `/goalspec` runs on an Opus-4.8 main spawned the adversary with `model: sonnet` (and once with no
  override), and the subagent ran `claude-haiku-4-5` **regardless** — the spawn `model` override was
  dropped by the environment, not by goalspec. The self-report caught it honestly (that mechanism
  worked). The subagent backend can't produce a capable adversary in such a host, but the **external
  backend runs as a shell CLI, not a subagent**, so it sidesteps the pin entirely. Global config makes
  "always use the external adversary" a one-time choice instead of a per-project chore — turning the
  only working path on such hosts into the default the user actually wanted. (The weak-tier pin itself
  is a host bug to fix separately; goalspec's side already did the right thing.)

## [0.10.0] - 2026-07-18

### Changed
- **Ratify gate blast-radius: phrase it for a non-technical user, and a counts-anchored size label —
  never a time estimate.** The audited user's wrong expectation came from authorizing a loop without
  gauging its size. The ratify gate (0.8.0) already shows the blast-radius (*"~80 columns across ~20
  tables + a deploy"*) — this makes that legible to a non-technical reader (*"this changes about 80
  things across your database and pushes to production — not something we can easily undo"*: what it
  touches + whether it's reversible, not jargon), optionally with a coarse **small / substantial /
  large** label anchored **strictly to countable structure** (things touched, reversible vs terminal).
- **Explicitly bans a time/effort estimate.** An earlier draft of this release tried a human-effort
  *time* band per option. Three consecutive different-model adversary rounds broke it as ungrounded:
  converting enumerated structure → a time band needs a per-unit human-effort rate an LLM has no
  calibration for, and coarse buckets don't absorb it (even "80 columns" spans ~1.3h–13h across three
  buckets depending on an unknowable per-column rate — false precision just relocated from the agent's
  own ETA). The convergence guard ("three breaks → the design is wrong, not the wording") retired the
  time approach entirely. What *is* groundable — and equally dimensioning for a non-technical user —
  is countable structure (how much a change touches, and reversibility), which the agent knows from
  the coverage floor. So the plugin dimensions by *what it touches*, never by *how long it takes*. A
  fitting close: the minimal-fix lens shipped in 0.9.0 caught this very release starting to build an
  estimation subsystem when a phrasing touch on existing blast-radius was the whole fix.

## [0.9.0] - 2026-07-18

### Added
- **Surface-the-minimal-fix lens (Q2) — the systemic frame must not eat the symptom-fix option.**
  Q1 ("real objective behind the narrative") is a reframing lever: right when the user *under*-scoped
  (shallow symptom, deep cause). Its opposite trap is subtle — and, importantly, it is **not** "the
  agent went deep without asking." In the audited session goalspec's clarify step *did* surface scope
  choices, and the user chose depth: they were explicitly offered *"Dejar histórico como está — cero
  riesgo sobre prod"* and picked *"Migración segura acotada (Recommended)"* + *"Implementar, testear y
  deployar (Recommended)"* themselves. The real gap is narrower and grounded: the agent offered three
  *sizes* of production migration but **never put the genuinely minimal option on the table** — a
  reversible read-layer fix for the one timestamp the user actually complained about, touching no prod
  data. The systemic frame pre-empted the symptom-fix, so the user could pick *how big a migration* but
  never *migration vs. no migration at all*. New Q2 lens: name **both** the smallest reversible fix for
  the reported symptom and the systemic fix, and make the minimal one a real choice via the ratify gate.
  Deliberately **not** "always ship the band-aid" — if the minimal fix is genuinely insufficient for a
  correctness the user needs, say so; the point is an honest fork with blast-radius visible, so the
  *user* chooses depth rather than depth being chosen by omission. **Enforced:** the `goal-adversary`'s
  No-harm check now flags executing a systemic/irreversible fix while the minimal option was never
  surfaced — with two mandatory guards (don't flag when the minimal fix was genuinely insufficient and
  they said so; don't flag when the minimal option *was* surfaced and the user chose depth). Requested
  by the user after this audit; the first draft of this lens ("default to minimal, systemic is opt-in")
  was caught by the different-model adversary as ungrounded (it contradicted 0.8.0's own transcript
  finding that the reframe was the method working) and unsafe (it licensed shipping band-aids over
  genuinely-required fixes) — this is the corrected form.

## [0.8.1] - 2026-07-18

### Fixed
- **Stop gate: anchor the completion-review on the LAST declaration, not the first `re.search` match.**
  Found by dogfooding 0.8.0's own close. `hooks/gate-goal-close.sh` builds its scan text as
  `last_assistant_message + entire transcript`, then used `re.search` (first match) to pick the
  `[COMPLETION-REVIEW: …]` to validate — so an earlier *exploratory or malformed* declaration
  permanently poisoned the check even after a correct one was emitted. Concretely: a first summary
  wrote `model=different (Sonnet 5 / claude-sonnet-5, vs my Opus 4.8)` — the trailing `, vs my Opus
  4.8` made the claimed id longer than the adversary's `[ADVERSARY-MODEL: …]` self-report, so the
  substring match failed; a later, clean re-declaration could not rescue it because first-match keeps
  returning the earliest occurrence. The gate now selects the **current-turn** declaration
  (`last_assistant_message`) if present, else the **most recent** one in the transcript — a stale or
  malformed earlier marker can no longer poison a valid close. Verified: malformed-then-clean now
  passes; malformed-only and genuinely-unmatched-self-report still block. (Instrument-validity on the
  method's own tooling — the same class of defect the 4th derived pattern exists to catch.)

## [0.8.0] - 2026-07-18

### Added
- **"Ratify the spec before you execute" — the plan-mode checkpoint (root-cause fix).** New
  first-class step (4b) between *emit spec* and *execute*. Once the goal-spec is written, the user
  still hasn't seen what the terse request *became* — "resolve the dates" spec'd into an ~80-column
  migration + a prod deploy while the user only asked about a label reading "6h ago." Conditional
  (fires when the spec is non-trivial, contains a terminal/irreversible action, or the work outgrew
  the trigger request; skipped for trivial specs so it never adds ceremony to a one-liner) and
  portable (one `AskUserQuestion` summarizing objective + blast-radius + terminal action, with
  Approve / Narrow / Minimal-fix / Stop; least-irreversible default when a terminal action is
  present; native plan mode optional where the harness has it). This is the checkpoint the audited
  session lacked: the spec was correct and the execution competent, and it *still* felt like it
  "dragged on for an hour" purely because the user never got to approve the scope the (correct)
  reframe produced. Requested directly by the user after they read this audit.
- **"When the work outgrows the request" — signal the reframe early, don't run dark.** Companion
  section, derived from the same session (a "why does it say synced 6h ago?" the user misdiagnosed as
  a server-clock display bug, which goalspec correctly reframed into a real per-row
  timestamp-corruption migration across ~20 tables + a prod deploy). The transcript decomposed to
  **~1.5h of dense agent activity out of 8.26h wall-clock (~18%)**; the other ~82% was long gaps with
  no logged agent action. Crucially — corrected by the user's primary-source account — those gaps
  were **not** the user being away: they were **present and waiting**, interrupting mid-run (*"Listo?"*
  ×2) because the agent looked stuck while it worked silently or blocked on the ~100-min adversary run
  / deploy rebuild (the agent itself later opened with *"perdón — llevo rato en modo silencioso"*).
  So "it took too long" was dominated by **silent long-running stretches watched by a present user**,
  not by inefficient work. Fixes: (1) surface a **cheap coarse fork** before sinking the full
  coverage-floor enumeration; (2) drop a **one-line progress beat** at natural checkpoints so a long
  silence never reads as "abandoned."

### Changed
- **Least-irreversible default for scope/terminal forks.** The `AskUserQuestion` convention "make the
  first option the recommended default so the user can proceed in one click" one-click-shipped a
  **production deploy** in the audited session (the *Alcance* modal defaulted to "Implementar, testear
  y **deployar** (Recommended)"). The rule now carries a hard exception: for a **scope** or
  **terminal-authorization** question, the recommended default is the **least-irreversible option that
  still meets the confirmed objective** — the terminal/maximal option goes in as an explicit
  *non-default* choice. Updated in all three carriers (clarify step, "Decisions you find mid-run",
  and the run-loop step-2 summary) per rule-surface enumeration. (Note: the audited session's
  *Históricos* modal already defaulted correctly to the conservative middle option — the footgun was
  isolated to the terminal-action question, so the fix is scoped there, not a blanket "default to
  smallest".)

## [0.7.1] - 2026-07-16

### Fixed
- **Third transcript-identity trap: never disown the parent by content overlap.** During the 0.7.0
  release verification itself, the different-model adversary excluded the executor's live session
  file from its ask sweep after finding its own spawn-prompt text inside it — reading "contains the
  text I was launched with" as "this is my own transcript". The inference is exactly backwards: the
  parent session *necessarily* records the `Task`/`Agent` `tool_use` that launched the subagent
  (prompt verbatim), and it keeps growing while the subagent runs because the main conversation is
  progressing. Two verification rounds were burned reporting a phantom missing-session while the
  `AskUserQuestion` pair sat in the dismissed file. The agent def now names the trap alongside the
  existing two (never newest-mtime, never text-grep) and upgrades the positive control to a
  mechanical identity check the adversary can run without trusting anyone: **find your own spawn
  record in the candidate file — the file that contains the prompt you actually received is the
  live parent, the one that must hold the ask.** The external backend's prompt carries the same
  rule for its stdin payload (overlap with your payload identifies the live parent; it does not
  make the file yours). The case-study reference (`references/instrument-validity-own-tools.md`)
  records the incident as **instance 6** — a carrier this release's own first pass left stale,
  caught by the verifying adversary running the rule-surface enumeration against the release
  itself (the 0.6.0 mechanism working as designed, on the doc that documents it).

## [0.7.0] - 2026-07-16

### Added
- **Size-aware grounding: an inline branch the spec previously didn't license.** "Ground yourself
  before you spec" modeled acquisition as binary — *skip* (terrain known) or *delegate* (subagent) —
  with inline reading existing only as the degraded no-subagent fallback. A user-reported
  production run on Fable exposed the gap (session-status evidence: grounding that needed ~10
  targeted operations — 1 pattern, 1 file read, 3 dirs, ~3.6k tokens at 7% context — was correctly
  done inline, against the letter of the spec), and the harness's own
  delegation policy ("single-fact / known-file lookups go direct; delegate when sweeping many
  files") actively steers that way. The step now sizes the acquisition first: **targeted** (you can
  name the exact few files/queries; what you read is what you keep) → inline; **broad** (you'd sift
  far more than you'll keep — many files, unknown locations, web research) → delegate. The test is
  **context hygiene, not command count** — spec-compliant behavior no longer costs a spawn that
  saves nothing.
- **Cheap tier for the explorer — the 0.5.0 adversary rule, mirrored.** The adversary spends
  capability *up* a tier because independence is its product; the explorer saves capability *down*
  a tier because its output is re-derived input. Mechanical explorations (locate/enumerate/cite)
  now default to a `model` override targeting a cheaper tier (`haiku`-class or the harness's
  smallest); judgment-heavy explorations (weighing prior-art, characterizing subtle behavior) keep
  the session tier — a cheap model that mis-summarizes terrain poisons the spec it was meant to
  ground. Deliberately **no self-report and no marker**, unlike the adversary: a silently-ignored
  override loses nothing because the explorer's independence is not load-bearing (its synthesis is
  re-derived input either way, and stays subject to the red-team and the adversary).

## [0.6.0] - 2026-07-16

### Added
- **Fourth derived pattern: instrument-consumer trace + rule-surface enumeration.** Five defects
  shipped in this method itself had one shape — an instrument requesting evidence that nothing
  consumes, or whose input can be satisfied by non-evidence (see the new
  `references/instrument-validity-own-tools.md` for the case study). The red-team's "turn this on
  your own instruments too" phrase demonstrably did not prevent instance 5 (it shipped *during*
  the release fixing its neighbor, and was caught by two independent Sonnet passes, not by the
  method). The mechanism is **conditional — it fires only when the change adds or modifies an
  instrument or a written rule**, so a run that touches neither pays nothing (user-ratified
  design). Executor side: for each instrument touched, name the consumer of every emission and
  check the consumer can't be satisfied by non-evidence; for each rule changed, grep its key terms
  and update or exempt every carrier found. Adversary side (subagent def + external prompt): the
  same sweep run from outside, with `ungrounded` for consumer-less emissions and `incomplete` for
  stale rule carriers.
- **Both empirical branches of 0.5.0 observed live.** (a) The installed 0.5.0 agent def emits
  `[ADVERSARY-MODEL: …]` **spontaneously** — a spawn prompt that never mentioned the self-report
  got it anyway, corroborated by 24/24 `"model":"claude-sonnet-5"` entries in the subagent's own
  transcript (the 0.4.0 def omitted it twice even under explicit prompting; contract-in-def works
  where contract-in-prompt didn't). (b) The `UNVERIFIABLE-BY-THIS-BACKEND` abstention branch was
  exercised for the first time with a partner that **genuinely** could not read the session log
  (an OS-level sandbox denying reads under `~/.claude/projects`): the partner diagnosed the exact
  scope of its own blindness, reported UNVERIFIABLE, and did **not** count the unverifiable ask —
  honest abstention, exactly as specified.

### Changed
- Step-6 tier examples generalized to a dynamic rule that doesn't age: "running any tier above
  Sonnet-class → spawn `sonnet`; running Sonnet-class or below → spawn `opus`" — no model-family
  names to fall out of date (user-ratified over naming new families explicitly).

## [0.5.0] - 2026-07-16

### Added
- **Different-model adversary by default for terminal actions — zero install, zero config.** The
  evidence (v0.4.0, recorded in the repo memory): 6 same-model fresh-context adversary rounds
  accepted a false load-bearing premise — round 6 explicitly blessed it — and a different model
  refuted it on first contact, by doing the thing the premise called impossible. Fresh context buys
  independence from the *conversation*, never from the *model's priors*. Yet the only
  different-model path was opt-in, config-gated, and dependent on an external CLI that can be absent
  or broken. Now, when closing a terminal/irreversible decision, the executor reads its **own**
  model from its context and spawns `goal-adversary` with a per-spawn `model` override on a
  different tier (Opus-class executor → `sonnet`; Sonnet-class or below → `opus` — verification is
  the wrong place to save capability). Verified by controlled experiment before building: identical
  probes to the plugin-provided agent, differing only in the override, self-identified as Sonnet 5
  vs the executor's Opus 4.8.
- **`[ADVERSARY-MODEL: <name> / <id>]` self-report opens every adversary output** (subagent and
  external backend both). The routing parameter is *not* evidence that routing happened: the harness
  documentedly **falls back silently** to the inherited model when an override can't be honored, and
  `external_cmd` can be a broken wrapper. Only the partner can attest what it is. The executor
  copies the self-report — never the spawn parameter — into the completion-review as
  `model=different (<id>)` or `model=same`.
- **The self-report has mechanical teeth, not just prompt text** — added after two *independent
  Sonnet reviews of this very change* converged on the same finding: the model line was requested in
  three prompts and enforced by zero code paths (the exact "check without evidence intake" failure
  the method warns about). Now `external-adversary.sh` extracts `[ADVERSARY-MODEL: …]` (rejecting
  the prompt's own `<model name>` template, as `VERDICT_RE` rejects `<n>`) and flags its absence on
  stderr as independence-UNVERIFIED; and the Stop gate cross-checks a `model=different (<id>)`
  completion-review claim against a matching self-report in the turn — advisory, fail-open, like
  every other gate branch.

- **A `hold` must show the work — the bare-hold gap is closed the same way.** Real case: a partner's
  third round returned a naked `hold` with zero bullets after two rounds of showing all its work.
  Now the agent contract states a hold's bullets change subject (what was attacked, what held) rather
  than disappear; `external-adversary.sh` mechanically flags a verdict with no evidence lines above
  it as UNVERIFIED on stderr (a floor, not proof of diligence — filler can game it; the lever remains
  the executor treating UNVERIFIED as UNVERIFIED); and the skill instructs the executor to never cite
  a bare hold as verification. Found in round 2 of this release's own dogfooding: the adversary
  caught the executor closing over the open pendiente that documented this exact gap.

### Changed
- **Degradation is announced, never silent** (fail-open preserved): same-or-UNKNOWN self-report →
  the verdict still counts, but the completion-review must disclose `model=same` — the exact pattern
  of the external backend's UNVERIFIED hold. No harness override, single-model account, non-Claude
  harness: proceed same-model and say so. Nothing blocks.
- **`external` backend repositioned, not demoted**: the subagent override decorrelates across tiers
  of one family; `external` decorrelates across **vendors** — still the strongest form and the only
  lever left on a single-model harness. (The backend that caught the v0.4.0 premise stays exactly
  where it was.)

## [0.4.0] - 2026-07-16

### Added
- **"Decisions you find mid-run — route them, don't narrate them" — the ask door no longer closes
  when the spec is committed.** Observed failure: after emitting the goal-spec, the agent would
  surface real forks in prose ("two decisions are yours"), list them well, and keep going — the
  human got a paragraph, never a question, and the run closed with the decision dangling. The
  mechanism was structural, not a lapse: (1) the only section teaching `AskUserQuestion` was titled
  "Clarify **before** you commit" and sat at step 2, so a fork *discovered during the work* — which
  is where most real forks live — had no affordance left; (2) Q5 asked the agent to *classify* which
  part is a human decision, and Completeness was satisfied by "every factor has an owner", so
  labeling owner=human **felt like discharging it**; (3) all mechanical pressure at close pointed at
  the `[COMPLETION-REVIEW]` marker, so an unasked decision cost the agent nothing. A new section
  makes the ask door stay open for the whole run, with a **decision-vs-doubt test** (route what turns
  on their intent/priorities/authorization *and* changes the work; never route what you can settle by
  reading the repo — that violates Autonomy just as hard), batching, recommended defaults, and
  "asking ≠ blocking".

### Changed
- **Q5 (Autonomy) reframed from labeling to routing** — naming a human decision is a *promise to
  ask*, not a filing category. An unasked decision is not owned.
- **The red-team gained the mirror check** — the Autonomy self-critique asked only "am I handing a
  human something an agent could execute?" (over-delegating). It now also asks the inverse: did I
  name a decision as theirs and never ask it?
- **`goal-adversary` now counts a dead handoff as an `autonomy-violation`** — both directions of the
  Autonomy failure are attackable, and a new mechanical **dead-handoff sweep** takes every Q5 human
  decision plus every fork the outcome hands the user and demands the place it was actually *asked*.
  Per the method's own philosophy (`references/outcome-loop-beats-gates.md`), the teeth go in the
  independent adversary, not in another Stop-hook regex over natural language.
- **The adversary verifies the ask against the session transcript — a source the executor doesn't
  author.** Found by running the adversary on this very change, twice; it returned `break` both times.
  First pass: the dead-handoff sweep had been added to an instrument that couldn't see the thing it
  checked — the adversary was handed only the goal-spec, the outcome, and the location of the work, so
  its only evidence was the executor's prose about the decision, the exact artifact the check exists
  to distrust. Second pass, on the fix for the first: adding an executor-supplied "ask record" to the
  intake **moved the trust without grounding it** — prose-A ("I surfaced it") became prose-B ("I asked
  at X, they said Y"), and both are text the executor types, so a narrating agent and an asking agent
  stayed indistinguishable. The adversary proved the real ground-truth was two commands away, and that
  the file already knew the pattern: the sibling inherited-decision sweep (`goal-adversary.md:24`) says
  "glob for them… grep them **yourself**". So the dead-handoff sweep now has the same **self-discovery verb** — it locates
  the session transcript itself and greps for the `AskUserQuestion` tool_use / tool_result pair. The
  executor's record is demoted to a *pointer to check*. An ask claimed but unverifiable in a source the
  executor doesn't control counts as a violation, per the agent's standing "uncertain → `break`" rule.
  A third pass then broke *that*: the hand-derived transcript path was wrong (`.` also maps to `-`, so
  any dotted cwd missed the glob — and combined with the new fail-closed rule that manufactures
  spurious `break`s), and the sweep never scoped to **this run**, while its sibling action-marker check
  (`goal-adversary.md:23`) does — this repo's transcript dir holds three sessions, all three containing
  an `AskUserQuestion`, so
  a prior session's ask would have blessed an agent that narrated today. The sweep now identifies the
  live transcript **by content** instead of trusting a derived path, and scopes the search to this
  session. A fourth pass then *executed* the instruction and landed on the wrong file — proving the
  newest-mtime tiebreak was a systematic anti-selector (subagent logs are written while the adversary
  runs, so they are always newer than the parent, and a subagent has no `AskUserQuestion` tool, so they
  can never contain an ask), and that a text-grep blesses prose that merely quotes the question. The
  sweep now reads the top-level session file only, matches the `tool_use`/`tool_result` **structure**
  rather than text, and requires a **positive control** — confirm you are reading the live session log
  before concluding an ask is absent, because a broken instrument is a null result with two disjoint
  causes, not proof of a dead handoff. "Confirmed dead handoff" and "unverifiable claim" are now
  reported as distinct outcomes (both count, but the executor can tell which to fix).
- **The `external` adversary backend carries principle 4 too — and is honest about the one check it
  can't run.** `hooks/external-adversary.sh` had kept principle 4 in its pre-fix, one-directional form
  ("nothing an agent could execute should be handed to a human"), so every user on
  `adversary.backend: "external"` would have gotten none of this while the changelog claimed both
  directions were attackable. Caught by the fourth adversary pass as a coverage-floor miss: the two
  documented backends were never enumerated. The fifth pass then broke the first repair — the
  *principle text* had shipped to the external backend but not the *evidence path*: an external CLI runs
  outside the session, so the positive control ("confirm you're reading **this** run's log") has no
  "this run" to anchor to, and the script piped only goal-spec + outcome anyway. Under the script's
  standing "cannot verify → count it" rule that would have manufactured a `break` on a genuinely correct
  ask. So: the ask record is now piped to the external partner, and principle 4 there tells it the ask
  record is a pointer, to **test its reach** and go read the session log if it can, and to report
  `UNVERIFIABLE-BY-THIS-BACKEND` (not counted) only if it genuinely cannot — an unreachable instrument
  is not a finding, but an unchecked one is just laziness.

### The correlated-bias result (why the `external` backend earns its keep)

Six adversary rounds were run against this change, all same-model fresh-context subagents. They found
five real defects. Then a **different model** (`claude -p --model claude-sonnet-5`, via the external
backend) was run on the same outcome — and refuted a premise all six had accepted:

- v0.4.0 had asserted, as fact, that an external partner "runs outside the session, so it cannot read
  the session log," and built the whole `UNVERIFIABLE-BY-THIS-BACKEND` carve-out on it. Adversary #6
  explicitly blessed it as "a real engineering decision, not a rationalization."
- The Sonnet partner falsified it **by doing the thing the design called impossible**: it read the live
  session log and located the `AskUserQuestion` tool_use/tool_result pairs itself. `claude -p` is a
  different *model*, not a different *machine* — same host, same filesystem, same tools.

The carve-out is therefore now **capability-conditional, not backend-conditional**. More importantly,
this is the correlated-bias failure the external backend exists to prevent, demonstrated on the
backend's own documentation: the subagent adversary is context-independent but **model**-correlated, and
six rounds of it could not see a premise the model found plausible. `references/external-adversary-setup.md`
now records this rather than claiming the backends are interchangeable.

### Fixed — instrument-validity in the external backend's own rails

Found by finally smoke-testing `external-adversary.sh` against real CLIs (an item deferred since
2026-07-08; the stub-`cat` test that preceded it proved only that the payload arrives):

- **A present-but-broken CLI produced no verdict at all.** The "missing binary → fail-open" rail checks
  `command -v`, which only proves a *wrapper* is on PATH. A `codex` whose vendored binary is missing
  passes that check, then dies with `ENOENT`, exit 1, and **no `[ADVERSARY-VERDICT:]` line** — handing
  the caller silence that reads as "no objection". The script now captures the run and requires a
  **filled** verdict; a non-zero exit or a malformed reply degrades to an explicit `hold` labelled
  UNVERIFIED, with the partner's output on stderr. (The rail claimed to handle exactly the
  instrument-validity failure it was blind to.) The first cut of this rail was itself broken, and the
  Sonnet partner caught it by *testing* rather than reading: it matched `grep '\[ADVERSARY-VERDICT:'`,
  but **the prompt contains that literal string** as the grammar template — so any CLI that echoes its
  stdin and exits 0 (a debug wrapper, or a plain `cat`) passed the gate and had its unfilled
  **placeholder** printed back as a real verdict. The pattern now demands `(break|hold)` plus numeric
  counts (rejecting both `break|hold` and `<n>`) and takes the last match, so a partner that quotes the
  grammar before answering still resolves to its real verdict. Six branches are covered by test: broken
  binary, missing binary, echo-the-prompt, chatty-no-verdict, quote-then-answer, and well-formed.
- **`gemini -p` was documented as a working `external_cmd` and cannot work.** It takes the prompt as an
  argument, not on stdin, so it can never receive a piped payload. The reference now ships a one-line
  adapter instead of a broken recipe, and flags that `codex`'s install should be verified by running it.
- **Dead-handoff detection is semantic, not a phrase list.** Also found by the adversary: the first
  cut shipped English-only literals (`"your call"`, `"up to you"`) — which would have missed the
  Spanish run that motivated the whole change ("dos decisiones que son tuyas"), while the changelog
  justified skipping hook teeth precisely *because* cross-language regex is fragile. The rationale and
  the artifact didn't reconcile. Both the self-red-team and the adversary now read for the **act**
  (did this sentence put a choice on the human?) in whatever language the executor writes; the phrases
  are illustrations, not the detector.
- The GOOD worked example now models raising the decision as a modal at the decision point, rather
  than as a line in the summary.

### Added — two holes this release's own dogfooding exposed

- **Q2 criteria now get gamed before they are committed.** Nothing in the method red-teamed the *spec*;
  the adversary only ever attacked the *outcome*, by which point the criteria were set. This release
  proved the cost: every one of its own success criteria was "text present in a file" while its
  objective was behavioural — five criteria the executor could satisfy with the very edits it was
  already making. The adversary caught it by quoting the constitution back (`SKILL.md:14`,
  *"marker present" ≠ done*), and it was only closed by running the acid test. Q2 now carries the test:
  *what would a lazy agent do to satisfy this without achieving the objective?* If the answer is "make
  the edit I was already going to make", it is a marker. The tell is an objective describing a
  behaviour against a criterion grepping for text.
- **A convergence guard on the break loop.** Nothing said when to stop patching. This change took five
  consecutive `break`s where **each round broke the previous round's fix** — a loop that could have run
  indefinitely, since every individual patch looked like progress. Step 6 now says: each round should
  break something smaller than the last; at three consecutive breaks the design is wrong, not the
  wording — reconsider the approach or route to a different model.
- **Instrument-validity turned on the method's own tools.** The red-team now asks it explicitly. Every
  expensive defect in this release was the method failing to audit its own instruments: a dead-handoff
  check with no evidence intake, a transcript rule that selected a file that could not hold the
  evidence, a fail-open rail blind to a broken CLI, a verdict gate matching its own prompt template.

### Not changed (deliberate)
- **The Stop gate is untouched.** Detecting "a decision was named" from prose is a regex over natural
  language (and over whatever language the user works in) — fragile, false-positive-prone, and
  exactly the "gate your way out of specification gaming" this method rejects.
- No loop steps were renumbered (the fix folds into existing steps 5, 6 and 7), so the `step N`
  cross-references in `README.md` and `references/external-adversary-setup.md` stay valid.

## [0.3.0] - 2026-07-14

### Added
- **"Ground yourself before you spec" — the agent can now acquire missing context before it commits
  the goal-spec.** A new pre-spec step: if any load-bearing Q2 (success) or Q3 (pre-mortem) claim
  depends on context the agent doesn't have firsthand — how the repo/codebase actually works, what
  the real ground-truth source contains, or the external prior-art / community best-practice — it
  delegates a *bounded* exploration to a fresh-context subagent via the Task tool (whatever agent
  type the environment provides: an `Explore`-style read-only searcher if present, else a
  general-purpose agent) and folds the synthesis into its criteria and pre-mortem. This stops the
  agent from spec-ing off a thin context, which is where shallow goal-specs come from.
- Guardrails baked in so this stays true to the method, not a new rule: **conditional** (skip if you
  already know the terrain — stays a lightweight prefix, not "always investigate"); **fail-open**
  (no subagent / no web / headless → do what you can and record the gap in the Assumptions line);
  **mechanical teeth** (the test is that Q2/Q3 visibly reflect what was found, not a "did I research"
  checkbox); and an explicit firewall — this forward **helper shares the host's frame and is NOT the
  independent adversary**; its output is re-derived and still passes the red-team/adversary before
  close. No new governance marker; it's an application of Grounding + Falsification + Autonomy.

## [0.2.3] - 2026-07-08

### Changed
- **Trigger description now lists common domains instead of a niche one.** 0.2.1 listed
  "even a water-treatment plant" as a domain example — memorable, but too niche for a trigger
  (it signals "for weird edge cases" rather than breadth). Replaced with the domains where users
  actually are: software engineering, data and analytics, marketing, research, writing, and product
  and business decisions. (The water-treatment worked example stays in the adaptation guide, where
  it usefully proves domain-independence.)

## [0.2.2] - 2026-07-08

### Fixed
- **Broken YAML frontmatter in 0.2.1.** The optimized description contained `not just code: software`
  — a colon-space that YAML parses as a mapping, so the skill loaded with **empty metadata** (the
  description was silently dropped, killing auto-trigger). Replaced the colon with a dash. Added a
  frontmatter YAML-parse check to the release routine so this can't recur. Anyone who pulled 0.2.1
  should update to 0.2.2.

## [0.2.1] - 2026-07-08

### Changed
- **Optimized the skill's auto-trigger description** (reviewed via the official skill-creator method).
  The old description listed task *types* but no *domains*, so it read as software/ops jargon and
  risked silently under-triggering on marketing/copywriting/ops/research tasks — undermining the
  zero-config-any-domain design. The new description names explicit domains, adds real-world trigger
  phrasings ("should I kill/ship/publish Y", "figure out why Z dropped", "review this before I
  merge"), and is more directive ("Trigger it whenever…") to counter Claude's known tendency to
  under-trigger skills — while keeping the anti-false-fire clause (no contentless "continue" turns,
  no trivial one-step lookups). Methodology in the body is unchanged.

## [0.2.0] - 2026-07-08

### Changed
- **Renamed the plugin `goal-elaboration` → `goalspec`, and made the skill the single entry point.**
  Claude Code mandates that plugin commands are namespaced (`/plugin:command`), so the old
  `commands/goalspec.md` was only reachable as `/goal-elaboration:goalspec`. Because a skill whose
  name equals its plugin's name renders un-namespaced, naming both `goalspec` makes the skill
  invocable as a clean `/goalspec` (it also auto-triggers). The standalone command was removed and
  its runbook folded into the skill. **Install id is now `goalspec@goal-forge`** — early installers
  of `goal-elaboration@goal-forge` should `uninstall` the old id and install the new one.
- **Zero-config for any domain.** The skill no longer requires `.claude/goal.config.json`. It now
  infers everything domain-specific from the task itself: ground-truth sources (named per-task),
  files to sweep (discovered by globbing decision/TODO/pending docs), which entities to enumerate
  (the task noun), and which actions are terminal (judged per-action). Config survives only as an
  optional power-user override for pinning exact sweep files or selecting an external adversary
  backend.

### Added
- **Clarifying-questions step (anti-drift).** Before committing to a goal-spec, the agent resolves
  load-bearing ambiguity (objective / scope / terminal-action authorization / done-bar) via the
  `AskUserQuestion` modal — so a 30-second question prevents an hour of misdirected work. Balanced
  threshold; when the task is clear it states its assumptions inline instead. Degrades gracefully in
  headless/cron runs.
- **Agent-guided install instructions** in the README: a top-of-file comment for AI agents plus
  terminal-form `claude plugin` commands, team/manual/dev install paths, and uninstall.
- Plugin manifest now carries `repository`, `license`, and `keywords`.

## [0.1.0] - 2026-07-08

### Added
- Initial release: the 5-principle constitution + 6-question goal-spec scaffold + red-team
  (`skills/goalspec`), an independent `goal-adversary` subagent (subagent or external-CLI
  backend), the `/goalspec` command, and a fail-open, transcript-anchored Stop completion gate.
  Genericized from a validated fleet pilot; no control-plane coupling.
