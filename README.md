# qa-banca-skyvern

Automatización QA para una banca demo desplegada en Minikube usando **Gherkin en español + pytest-bdd + Skyvern + Ollama**.

El objetivo del proyecto no es delegar todo el escenario a un agente. El framework interpreta operaciones conocidas y decide qué primitiva utilizar (`goto`, `fill`, `click`, `extract`, `validate`). Skyvern y el LLM se utilizan donde aportan valor: localizar elementos, interpretar estado visible y extraer información de la UI. `page.act()` queda como fallback para acciones no modeladas.

## Qué demuestra el lab

- Escenarios funcionales escritos en Gherkin.
- Ejecución real contra la aplicación desplegada en Minikube.
- Datos diferentes por escenario mediante perfiles lógicos.
- Localización semántica de elementos con Skyvern.
- Escape hatch determinístico mediante `id` o selector CSS.
- Extracción de valores de la UI durante la ejecución.
- Validaciones determinísticas en Python para reglas de negocio.
- Evidencia HTML/JSON y screenshots por step.
- Un escenario fallido no detiene el resto de la suite.

## Arquitectura

```text
.feature (Gherkin)
        |
        v
    pytest-bdd
        |
        v
    StepRouter
        |
        +---- goto / fill / click ----------> SkyvernPage
        |
        +---- extract ----------------------> Skyvern + LLM
        |                                      |
        |                                      v
        |                               VariablesEscenario
        |                                      |
        |                                      v
        |                               asserts en Python
        |
        +---- validate --------------------> Skyvern + LLM
        |
        `---- act -------------------------> fallback agentic
                                               |
                                               v
                                            Browser
                                               |
                                               v
                                      Banking app / Minikube
```

La explicación detallada está en [`docs/arquitectura.md`](docs/arquitectura.md).

## Requisitos

- Python 3.11+
- Docker
- Minikube con la banca demo desplegada
- Skyvern self-hosted
- Ollama con un modelo compatible con Skyvern

Para el proyecto Python:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuración QA

Crea el archivo local:

```bash
cp .env.example .env.qa
```

Ejemplo:

```env
BASE_URL=http://192.168.49.2:30081/

SKYVERN_BASE_URL=http://localhost:8000
SKYVERN_API_KEY=...

SMOKE_LOGIN_PERSONAL_USERNAME=cliente
SMOKE_LOGIN_PERSONAL_PASSWORD=...

SMOKE_TRANSFER_USERNAME=cliente_transfer
SMOKE_TRANSFER_PASSWORD=...
SMOKE_TRANSFER_OTP=1245
```

`.env.qa` debe permanecer fuera de Git. En CI/CD los valores sensibles deben provenir del secret store o de variables protegidas del pipeline.

## Datos por escenario

Los datos de entrada viven en `data/profiles.yaml`.

```yaml
profiles:
  smoke_login_personal:
    username: env://SMOKE_LOGIN_PERSONAL_USERNAME
    password: env://SMOKE_LOGIN_PERSONAL_PASSWORD

  smoke_transfer:
    username: env://SMOKE_TRANSFER_USERNAME
    password: env://SMOKE_TRANSFER_PASSWORD
    otp: env://SMOKE_TRANSFER_OTP
    amount: 25000
```

El escenario selecciona un perfil lógico:

```gherkin
Dado que la prueba se ejecuta con el perfil "smoke_transfer"
```

El `.feature` no necesita conocer nombres de variables de ambiente ni secretos reales.

## Vocabulario genérico del StepRouter

El router conoce **operaciones**, no conceptos de banca.

| Gherkin | Ejecución |
|---|---|
| `Dado que la prueba se ejecuta con el perfil "X"` | `DatosPrueba.usar("X")` |
| `Y navego a la aplicación` | `page.goto(BASE_URL)` |
| `Cuando ingreso la variable "username" en "Username"` | `page.fill(prompt=..., value=...)` |
| `Cuando ingreso la variable "username" en el elemento con id "username"` | `page.fill("#username", value=...)` |
| `Cuando ingreso la variable "x" en el elemento con selector "..."` | `page.fill(selector, value=...)` |
| `Cuando hago click en "Continue"` | `page.click(prompt="Continue")` |
| `Cuando hago click en el elemento con id "continueButton"` | `page.click("#continueButton")` |
| `Cuando hago click en el elemento con selector "..."` | `page.click(selector)` |
| `Cuando guardo el valor de "..." como "saldo_inicial"` | `page.extract(...)` + `VariablesEscenario` |
| `Entonces la variable "a" debe ser igual a la variable "b" menos la variable "monto"` | assert determinístico en Python |
| otro `Entonces ...` | `page.validate(...)` + assert de pytest |
| otro `Cuando ...` | `page.act(texto)` |

La prioridad es:

```text
determinístico explícito
        ↓
operación semántica conocida
        ↓
fallback agentic
```

## Variables generadas durante un escenario

Los profiles representan **datos de entrada**. Los valores descubiertos durante el caso de uso viven en `VariablesEscenario`.

Ejemplo:

```gherkin
Cuando guardo el valor de "saldo de la cuenta origen terminada en 000002" como "saldo_origen_inicial"
Y guardo el valor de "saldo de la cuenta destino terminada en 000003" como "saldo_destino_inicial"

# ... se realiza la transferencia ...

Y guardo el valor de "saldo de la cuenta origen terminada en 000002" como "saldo_origen_final"
Y guardo el valor de "saldo de la cuenta destino terminada en 000003" como "saldo_destino_final"

Entonces la variable "saldo_origen_final" debe ser igual a la variable "saldo_origen_inicial" menos la variable "amount"
Y la variable "saldo_destino_final" debe ser igual a la variable "saldo_destino_inicial" mas la variable "amount"
```

Skyvern ayuda a **extraer** los valores. La aritmética la ejecuta Python con `Decimal`; no se delega al LLM.

Las variables runtime se crean por escenario y se destruyen al terminarlo.

## Ejecutar smoke

Solo escenarios `@smoke`:

```bash
TEST_ENV=qa pytest -s -m smoke
```

Combinaciones:

```bash
TEST_ENV=qa pytest -s -m "smoke and authentication"
TEST_ENV=qa pytest -s -m "smoke and transfers"
TEST_ENV=qa pytest -s -m "smoke and not negative"
```

## Manejo de fallos

Un step que no puede completarse mantiene el escenario como `FAILED`.

Ejemplo conceptual:

```text
Login usuario A                     PASSED
Transferencia cuenta inexistente   FAILED
Login usuario B                     PASSED
Consulta tarjetas                  PASSED

3 passed, 1 failed
```

El error se registra con:

- motivo legible para QA;
- step que falló;
- excepción técnica;
- screenshot;
- tiempo de ejecución.

No se utiliza `-x` ni `--maxfail=1`, por lo que pytest continúa con los demás escenarios.

## Evidencia

Cada corrida genera:

```text
evidencia/<fecha_hora>/
├── screenshots...
├── resumen.json
└── index.html
```

Las capturas pueden contener datos sensibles. `evidencia/` y `.env.qa` deben estar ignorados por Git.

## Infraestructura local

### Estado actual validado

La implementación que ya fue validada utiliza:

```text
pytest
  |
  +--> Skyvern SDK
  |      |
  |      +--> Skyvern self-hosted :8000
  |
  +--> Browser local
  |
  `--> Banking app / Minikube

Skyvern self-hosted --> Ollama
```

`support/browser.py` debe mantenerse alineado con la versión de Skyvern fijada en `requirements.txt`.

### Objetivo: stack reproducible con Docker

La siguiente evolución del lab es mover la infraestructura de IA a Docker Compose:

```text
Docker Compose
├── Skyvern API
├── Skyvern UI
├── PostgreSQL
└── Ollama
```

Dentro de la red Compose, Skyvern puede consumir Ollama mediante:

```text
http://ollama:11434
```

Esto elimina dependencias manuales del host y permite levantar la infraestructura con pocos comandos.

**Importante:** antes de cambiar a Skyvern completamente dockerizado hay que adaptar y validar `support/browser.py`. `launch_local_browser()` pertenece al modo de browser local; un Skyvern en contenedor debe preferir una sesión de navegador administrada por el servidor para evitar problemas de conectividad entre el contenedor y un browser abierto en `localhost` del host.

Por esa razón, la infraestructura Docker debe introducirse como un cambio controlado y probarse antes de convertirse en el quickstart principal.

## Docker Compose vs Terraform

Para este laboratorio:

```text
Docker Compose
→ ejecuta Skyvern, PostgreSQL y Ollama

Terraform
→ opcionalmente aprovisiona dónde corre el stack
   (VM, red, discos, firewall, etc.)
```

Terraform no aporta mucho valor para administrar directamente contenedores locales que Docker Compose ya describe de forma natural.

Una evolución cloud podría ser:

```text
Terraform
   ↓
VM / networking / storage
   ↓
cloud-init
   ↓
Docker + Docker Compose
   ↓
Skyvern + Ollama
```

## Mock

`mock-app/` se conserva únicamente como playground para aislar problemas de browser/modelo. El smoke real del proyecto se ejecuta contra Minikube.

```bash
node mock-app/server.js
```

## Versionado

Skyvern cambia con rapidez. Mantén la versión fijada en `requirements.txt` y valida `support/browser.py`, `support/step_router.py` y la integración con el modelo antes de actualizarla.
