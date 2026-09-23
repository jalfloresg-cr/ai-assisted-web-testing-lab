# Arquitectura de ejecución

Este proyecto usa **Gherkin + pytest-bdd + StepRouter + Skyvern + Ollama**.

El principio central es separar:

1. **qué quiere validar el escenario**;
2. **qué operación debe ejecutar el framework**;
3. **qué parte necesita interpretación por IA**;
4. **qué reglas deben validarse de forma determinística**.

La IA no decide todo el escenario.

## Flujo general

```text
.feature (Gherkin)
        |
        v
    pytest-bdd
        |
        v
    StepRouter
        |
        +------------------------------+
        |                              |
        v                              v
operaciones conocidas            fallback desconocido
goto/fill/click/                  page.act()
extract/validate                      |
        |                              |
        +---------------+--------------+
                        |
                        v
                  SkyvernPage
                        |
             +----------+----------+
             |                     |
             v                     v
        Playwright             Skyvern + LLM
             |                     |
             +----------+----------+
                        |
                        v
                     Browser
                        |
                        v
               Aplicación bajo prueba
```

## Responsabilidad del StepRouter

`StepRouter` debe ser **agnóstico al dominio**.

Debe conocer operaciones como:

```text
navegar
fill
click
extract
validate
act
```

No debe conocer:

```text
username
password
OTP
cuentas
tarjetas
menús
Transferencias
Product Summary
```

Estos términos pueden aparecer en el Gherkin como descripciones o nombres de variables, pero no deben quedar hardcodeados en el router.

## Niveles de interpretación

No se interpreta una palabra aislada. Hay distintos niveles.

### 1. Acción determinística

```gherkin
Cuando hago click en el elemento con id "continueButton"
```

El router produce:

```python
page.click("#continueButton")
```

El LLM no necesita localizar el elemento.

### 2. Acción conocida + localización semántica

```gherkin
Cuando hago click en "Continue"
```

El router ya sabe que la operación es `click`:

```python
page.click(prompt="Continue")
```

Skyvern/LLM decide qué elemento corresponde a `Continue`.

### 3. Fallback agentic

```gherkin
Cuando completo el flujo especial del producto
```

Si el router no tiene una regla conocida:

```python
page.act(texto)
```

En ese caso el agente tiene mayor autonomía y puede decidir tanto la acción como el elemento.

## Prioridad de ejecución

```text
selector explícito / id
        |
        v
primitiva conocida
(fill/click/extract...)
        |
        v
semántica con IA
        |
        v
page.act() como fallback
```

La intención es usar la menor autonomía necesaria para cada step.

## Vocabulario actual

| Patrón | Resultado |
|---|---|
| `la prueba se ejecuta con el perfil "X"` | `DatosPrueba.usar("X")` |
| `navego a la aplicación` | `page.goto(BASE_URL)` |
| `ingreso la variable "x" en "objetivo"` | `page.fill(prompt=objetivo, value=...)` |
| `ingreso la variable "x" en el elemento con id "y"` | `page.fill("#y", value=...)` |
| `ingreso la variable "x" en el elemento con selector "y"` | `page.fill("y", value=...)` |
| `hago click en "objetivo"` | `page.click(prompt=objetivo)` |
| `hago click en el elemento con id "y"` | `page.click("#y")` |
| `hago click en el elemento con selector "y"` | `page.click("y")` |
| `guardo el valor de "objetivo" como "x"` | `page.extract(...)` + variable runtime |
| validación matemática de variables | assert en Python |
| otro `Entonces` | `page.validate(...)` |
| otro `Cuando` | `page.act(...)` |

## Datos de entrada

Los datos de entrada se separan del Gherkin:

```text
.feature
   |
   | perfil lógico
   v
data/profiles.yaml
   |
   | env://VARIABLE
   v
.env.qa / secret store del CI
```

Ejemplo:

```gherkin
Dado que la prueba se ejecuta con el perfil "smoke_transfer"
```

```yaml
profiles:
  smoke_transfer:
    username: env://SMOKE_TRANSFER_USERNAME
    password: env://SMOKE_TRANSFER_PASSWORD
    otp: env://SMOKE_TRANSFER_OTP
    amount: 25000
```

`DatosPrueba` resuelve el profile. No conoce el DOM ni el navegador.

## Variables runtime

Hay una diferencia importante entre:

```text
DatosPrueba
→ entrada conocida antes del escenario

VariablesEscenario
→ información obtenida durante la ejecución
```

Ejemplo:

```text
amount = 25000
```

viene del profile.

En cambio:

```text
saldo_origen_inicial
saldo_origen_final
```

se obtienen de la aplicación.

### Extracción

```gherkin
Cuando guardo el valor de "saldo de la cuenta origen terminada en 000002" como "saldo_origen_inicial"
```

El router ejecuta conceptualmente:

```python
valor = extractor.extraer(
    "saldo de la cuenta origen terminada en 000002"
)

variables.guardar(
    "saldo_origen_inicial",
    valor,
)
```

Skyvern ayuda a interpretar la UI y devolver el dato estructurado.

### Validación determinística

```gherkin
Entonces la variable "saldo_origen_final" debe ser igual a la variable "saldo_origen_inicial" menos la variable "amount"
```

El LLM **no realiza la aritmética**.

El router resuelve los valores y Python ejecuta:

```text
expected = saldo_origen_inicial - amount
assert saldo_origen_final == expected
```

Para valores monetarios se utiliza `Decimal`.

Este patrón reduce falsos positivos:

```text
IA
→ encontrar / interpretar / extraer

Python
→ comparar / calcular / afirmar
```

## Ciclo de vida por escenario

Cada escenario recibe su propio:

```text
Sesion
DatosPrueba
VariablesEscenario
StepRouter
```

Por eso:

```text
Scenario A
variables = {...}
        |
        v
termina
        |
        v
estado descartado

Scenario B
variables = {}
```

No hay contaminación entre escenarios.

## Manejo de errores

Un step fallido no se convierte en PASS.

```text
step falla
   |
   v
pytest marca escenario FAILED
   |
   +--> motivo funcional
   +--> excepción técnica
   +--> screenshot
   +--> tiempo
   |
   v
teardown del escenario
   |
   v
pytest continúa con el siguiente test
```

Ejemplo:

```text
Smoke A   PASSED
Smoke B   FAILED
Smoke C   PASSED
```

El framework no utiliza `-x` ni `--maxfail=1` en la ejecución estándar.

## Evidencia

La capa de evidencia observa la ejecución, pero no decide el resultado.

```text
pytest-bdd hooks
     |
     +--> step
     +--> estado
     +--> tiempo
     +--> screenshot
     +--> motivo
     +--> detalle técnico
     |
     v
resumen.json + index.html
```

## Infraestructura actual

El runtime validado hasta ahora es:

```text
pytest
   |
   +--> Skyvern SDK
   |
   +--> browser local
   |
   +--> Skyvern self-hosted :8000
            |
            v
          Ollama

browser
   |
   v
Minikube banking app
```

La configuración exacta de `support/browser.py` debe mantenerse alineada con la versión fijada de Skyvern.

## Objetivo de infraestructura reproducible

La evolución deseada es:

```text
                  Docker Compose
         +-------------+-------------+
         |             |             |
         v             v             v
      Skyvern      PostgreSQL      Ollama
     API + UI         DB             LLM
         |
         v
 browser administrado por Skyvern
         |
         v
 Banking app / Minikube
```

La ventaja es separar claramente:

```text
framework QA
→ pytest / Gherkin / router

infraestructura AI
→ Skyvern / DB / Ollama
```

### Consideración importante sobre el browser

`launch_local_browser()` pertenece al modo de navegador local.

Si Skyvern se ejecuta dentro de Docker y pytest abre un browser en `localhost` del host, el contenedor no puede asumir que ese `localhost` es accesible.

Por eso, antes de convertir Docker Compose en el quickstart principal, `support/browser.py` debe migrar y validarse usando una sesión de navegador administrada por el Skyvern self-hosted.

Eso evita una arquitectura híbrida frágil:

```text
Skyvern container
      X
localhost browser del host
```

## Docker Compose y Terraform

### Docker Compose

Responsable de los servicios del lab:

```text
Skyvern API
Skyvern UI
PostgreSQL
Ollama
volúmenes
red local
healthchecks
```

Si Ollama y Skyvern están en la misma red Compose:

```text
OLLAMA_SERVER_URL=http://ollama:11434
```

### Terraform

Terraform se reserva para aprovisionar infraestructura donde ejecutar el stack:

```text
VM
networking
storage
firewall
DNS
```

Ejemplo:

```text
Terraform
   |
   v
VM + red + disco
   |
   v
cloud-init
   |
   v
Docker / Compose
   |
   v
Skyvern + Ollama
```

Para desarrollo local, Terraform no sustituye a Docker Compose.

## Principio de diseño

La arquitectura busca este equilibrio:

```text
natural language
      +
AI element discovery
      +
deterministic browser primitives
      +
deterministic business assertions
```

La IA se usa para reducir fragilidad frente a cambios de UI, pero el framework conserva el control de las operaciones conocidas y de las validaciones que pueden expresarse exactamente.
