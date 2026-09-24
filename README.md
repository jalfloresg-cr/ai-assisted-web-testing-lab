# qa-banca-skyvern

Automatización QA para una banca demo desplegada en Minikube usando **Gherkin en español + pytest-bdd + Skyvern + Ollama**.

El objetivo del proyecto no es delegar todo el escenario a un agente. El framework interpreta operaciones conocidas y decide qué primitiva utilizar. Cada step puede resolverse de forma **determinística** (selector CSS o id, sin LLM) o **semántica** (una descripción en lenguaje natural que Skyvern interpreta con el LLM). `page.act()` queda como fallback para acciones no modeladas y puede bloquearse con `ROUTER_STRICT=true`.

## Qué demuestra el lab

- Escenarios funcionales escritos en Gherkin.
- Ejecución real contra la aplicación desplegada en Minikube.
- Dos estilos de escritura combinables: por selector (sin LLM) o por descripción (con LLM).
- Datos diferentes por escenario mediante perfiles lógicos.
- Extracción de valores de la UI durante la ejecución.
- Validaciones determinísticas en Python para reglas de negocio.
- Modo estricto: ningún step se delega al agente sin que lo sepas.
- Evidencia HTML/JSON por feature, con screenshots y la ruta de resolución de cada step.
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
        +---- selector / id -----------------> Playwright (vía Skyvern)   sin LLM
        |
        +---- descripción --------------------> Skyvern + LLM             localiza el elemento
        |
        +---- extract / validate semánticos --> Skyvern + LLM             interpreta la pantalla
        |
        +---- asserts de variables -----------> Python (Decimal)          sin LLM
        |
        `---- act (fallback) -----------------> agente Skyvern + LLM      bloqueable con ROUTER_STRICT
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
HEADLESS=false
SKYVERN_TIMEOUT=600

# Router
ROUTER_STRICT=true           # un step sin regla falla en lugar de ir al agente
SELECTOR_TIMEOUT_MS=10000    # espera máxima de los steps por selector

# Datos por perfil (ver data/profiles.yaml)
SMOKE_LOGIN_PERSONAL_USERNAME=cliente
SMOKE_LOGIN_PERSONAL_PASSWORD=...
```

`.env.qa` debe permanecer fuera de Git. En CI/CD los valores sensibles deben provenir del secret store o de variables protegidas del pipeline. Para compartir el proyecto usa `git archive --format=zip HEAD -o proyecto.zip`, que solo incluye archivos versionados.

## Datos por escenario

Los datos de entrada viven en `data/profiles.yaml`. Los valores sensibles se referencian con `env://VARIABLE` y nunca se escriben en el YAML.

```yaml
profiles:
  smoke_login_personal:
    username: env://SMOKE_LOGIN_PERSONAL_USERNAME
    password: env://SMOKE_LOGIN_PERSONAL_PASSWORD

  smoke_transfer_personal:
    username: env://SMOKE_TRANSFER_PERSONAL_USERNAME
    password: env://SMOKE_TRANSFER_PERSONAL_PASSWORD
    otp: env://SMOKE_TRANSFER_PERSONAL_OTP
    amount: 25000
```

El escenario selecciona un perfil lógico:

```gherkin
Dado que uso el perfil de prueba "smoke_transfer_personal"
```

Luego cualquier step puede usar sus claves como variables: `ingreso la variable "username" en ...`. El `.feature` no conoce nombres de variables de ambiente ni secretos reales.

## Cómo escribir test cases

### Principios

- **El router conoce operaciones, no conceptos de banca.** Reconoce la *estructura* de la frase (`hago click en ...`), no palabras sueltas como "menú" o "botón".
- **`Dado` y `Cuando` comparten el mismo vocabulario de acciones.** La palabra clave expresa la intención para el lector (contexto vs. acción bajo prueba); no limita qué se puede hacer. `Entonces` tiene su propio vocabulario de validaciones.
- **El `que` inicial es opcional:** `Dado que hago click en ...` y `Cuando hago click en ...` se resuelven igual.
- **Cada step se resuelve de forma independiente.** Un mismo escenario puede mezclar estilos.

### Tres estilos

| Estilo | Cómo se escribe | LLM | Cuándo usarlo |
|---|---|---|---|
| **Por selector** | `hago click en el selector "#continueButton"` | No | Pantallas estables, datos críticos (saldos, montos), regresión |
| **Semántico** | `hago click en "botón Continue"` | Sí, para localizar el elemento | Escritura rápida sin inspeccionar el DOM, pantallas que cambian seguido |
| **Mixto** | Selectores en unos steps, descripciones en otros | Solo en los steps semánticos | La mayoría de los casos reales |

### Formas de indicar un elemento por selector

Las tres formas son equivalentes:

```gherkin
... el selector "#continueButton"                    # forma corta
... el elemento con selector "#continueButton"       # forma larga
... el elemento con id "continueButton"              # por id, con o sin "#"
```

- Dentro del selector usa **comillas simples**: `"[data-testid='sign-in']"`. Las comillas dobles cortan el step.
- Si el selector coincide con varios elementos, se usa el primero. Prefiere selectores únicos.
- Prioridad recomendada: `data-testid` > `id` > atributos accesibles (`[aria-label='...']`) > clases CSS. Evita XPath posicional.
- El riesgo conocido de este estilo: si cambia el DOM, hay que editar los features que usan ese selector.

### Vocabulario: contexto y navegación (`Dado` / `Cuando`)

| Gherkin | Operación | Ruta |
|---|---|---|
| `que uso el perfil de prueba "smoke_login_personal"` | Activa el perfil de datos | determinístico |
| `que abro la banca en línea` / `que abro la aplicación` / `navego a la aplicación` | `goto(BASE_URL)` | determinístico |
| `que navego a la ruta "/transfers"` | `goto(BASE_URL + ruta)` (solo rutas relativas) | determinístico |
| `regreso a la página anterior` | Botón "atrás" del navegador | determinístico |
| `recargo la página` | Recarga la página | determinístico |

El navegador lo abre el fixture de pytest antes del primer step, pero queda en blanco. **Algún step debe navegar**; lo habitual es ponerlo en `Antecedentes`.

La navegación exige la **frase completa**. `Dado que abro el menú de transferencias` *no* navega: es una acción sobre la UI y se escribe como click.

"Volver" usando la app (`hago click en "botón Volver"`) no es lo mismo que `regreso a la página anterior`, que usa el navegador.

### Vocabulario: acciones (`Dado` / `Cuando`)

| Gherkin | Por selector (sin LLM) | Semántico (con LLM) |
|---|---|---|
| Click | `hago click en el selector "#x"` | `hago click en "botón Continue"` |
| Escribir una variable | `ingreso la variable "username" en el selector "#x"` | `ingreso la variable "username" en "campo Username"` |
| Escribir un literal | `ingreso el valor "25000" en el selector "#x"` | `ingreso el valor "25000" en "campo Monto"` |

`clic` y `click` se aceptan por igual. Las variables se buscan primero entre las generadas en el escenario y luego en el perfil activo.

En el estilo semántico, lo que va entre comillas es una **descripción para el LLM**. Hazla descriptiva por sí misma: "botón Sign in" funciona mejor que "Sign in", y un texto como "btn1" no sirve. No pongas un selector CSS en una descripción: `hago click en "#menu"` se enviaría al LLM como texto.

### Vocabulario: extracción de datos

| Gherkin | Resolución |
|---|---|
| `guardo el texto del selector "#saldo-000002" como "saldo_inicial"` | Texto visible del elemento, sin LLM |
| `guardo el valor de "saldo de la cuenta terminada en 000002" como "saldo_inicial"` | El LLM interpreta la pantalla y devuelve el valor |

Para montos y datos críticos se recomienda la forma por selector: es exacta e instantánea.

### Vocabulario: validaciones (`Entonces`)

| Gherkin | Resolución |
|---|---|
| `el selector "#x" está visible` | Espera hasta `SELECTOR_TIMEOUT_MS` a que aparezca |
| `el selector "#x" no está visible` | Espera a que desaparezca o no exista |
| `el selector "#x" contiene el texto "Product Summary"` | Reintenta hasta que el texto coincida. Distingue mayúsculas; normaliza espacios y saltos de línea |
| `la variable "a" debe ser igual a la variable "b"` | Assert en Python |
| `la variable "a" debe ser igual a "1000000"` | Assert en Python (compara como número si ambos lo son) |
| `la variable "final" debe ser igual a la variable "inicial" menos la variable "amount"` | Aritmética con `Decimal` en Python |
| `la variable "final" debe ser igual a la variable "inicial" mas la variable "amount"` | Ídem |
| `la variable "a" debe ser mayor que la variable "b"` / `menor que` | Ídem |
| **Cualquier otro texto** | `page.validate()`: el LLM juzga si la condición se cumple |

La IA nunca hace la aritmética: extrae los valores y Python calcula y compara.

### Cuándo interviene el LLM

| Situación | ¿LLM? |
|---|---|
| Step por selector o id (click, fill, texto, visible, contiene) | **No** |
| Perfil, navegación, atrás, recargar, asserts de variables | **No** |
| Step semántico (descripción entre comillas) | Sí, para localizar el elemento |
| `guardo el valor de "..."` | Sí, para interpretar y extraer |
| `Entonces` en texto libre | Sí, para juzgar la condición |
| Step que no coincide con ninguna regla, con `ROUTER_STRICT=false` | Sí, como **agente** (`act`), con máxima autonomía |
| Step que no coincide con ninguna regla, con `ROUTER_STRICT=true` | No: el step falla como `sin_regla` |

**Garantía del estilo por selector.** Skyvern puede consultar al LLM aunque reciba un selector, pero solo si además recibe una descripción (`prompt`): en ese caso, si el selector falla, usa el LLM como respaldo. En los steps por selector el router envía **solo el selector**, así que si el selector no se encuentra, Skyvern reintenta y lanza el error original sin llamar al modelo. Esto está verificado en el código de Skyvern 1.0.48; al actualizar Skyvern hay que volver a comprobarlo.

Un error de escritura en la frase (por ejemplo, `hago clic en selector "#x"`, sin "el") hace que el step no coincida con ninguna regla. Por eso se recomienda `ROUTER_STRICT=true` siempre en smoke y CI.

Para confirmar que un escenario no usó el LLM, revisa la columna **Ruta** del informe: si todos sus steps son `deterministico`, no hubo llamadas al modelo.

### Ejemplo: estilo por selector

```gherkin
# language: es
@login
Característica: Login de banca personal

  Antecedentes:
    Dado que abro la banca en línea

  @smoke
  Escenario: Login exitoso con selectores
    Dado que uso el perfil de prueba "smoke_login_personal"
    Cuando ingreso la variable "username" en el selector "#username"
    Y hago click en el selector "#continueButton"
    Entonces el selector "#password" está visible
    Cuando ingreso la variable "password" en el selector "#password"
    Y hago click en el selector "[data-testid='sign-in']"
    Entonces el selector "#posicion-consolidada" está visible
    Y el selector "#error-login" no está visible
```

### Ejemplo: estilo semántico

```gherkin
  @smoke
  Escenario: Login exitoso descrito en lenguaje natural
    Dado que uso el perfil de prueba "smoke_login_personal"
    Cuando ingreso la variable "username" en "campo Username"
    Y hago click en "botón Continue"
    Entonces hay un campo de texto password para escribir la contraseña
    Cuando ingreso la variable "password" en "campo Password"
    Y hago click en "botón Sign in"
    Entonces se muestra la posicion consolidada con 2 Accounts y 1 CreditCards
```

### Ejemplo: estilo mixto con validación de negocio

```gherkin
  Escenario: Transferencia descuenta el saldo de la cuenta origen
    Dado que uso el perfil de prueba "smoke_transfer_personal"
    Y ingreso la variable "username" en el selector "#username"
    Y hago click en el selector "#continueButton"
    Y ingreso la variable "password" en el selector "#password"
    Y hago click en el selector "[data-testid='sign-in']"
    Y guardo el texto del selector "#saldo-000002" como "saldo_origen_inicial"
    Cuando hago click en "menú Transferencias"
    Y ingreso la variable "amount" en "campo Monto"
    Y hago click en "botón Confirmar transferencia"
    Entonces se muestra el comprobante de la transferencia
    Cuando navego a la ruta "/accounts"
    Y guardo el texto del selector "#saldo-000002" como "saldo_origen_final"
    Entonces la variable "saldo_origen_final" debe ser igual a la variable "saldo_origen_inicial" menos la variable "amount"
```

El login y la lectura de saldos usan selectores (exactos y sin LLM); el flujo de transferencia usa descripciones; la regla de negocio la verifica Python.

### Reglas de organización

- **Nombres de escenario únicos dentro de cada `.feature`.** Si dos escenarios del mismo archivo se llaman igual, pytest-bdd conserva solo el último y el otro **deja de ejecutarse sin aviso**.
- **Tags a nivel de `Característica`** para el área funcional (`@login`); se heredan a todos sus escenarios.
- **Tags a nivel de `Escenario`** para el tipo de suite (`@smoke`, `@regression`).
- **La `Característica` y su descripción** (Como / Quiero / Para) son documentación para el equipo: no se envían al LLM. Lo que sí afecta la ejecución son sus `Antecedentes` y sus tags.

## Variables generadas durante un escenario

Los perfiles representan **datos de entrada**. Los valores descubiertos durante el caso de uso viven en `VariablesEscenario`, se crean por escenario y se destruyen al terminarlo:

```text
DatosPrueba          → entrada conocida antes del escenario (amount = 25000)
VariablesEscenario   → obtenido durante la ejecución (saldo_origen_inicial)
```

## Ejecutar pruebas

```bash
TEST_ENV=qa pytest -s -m smoke                # solo smoke
TEST_ENV=qa pytest -s -m login                # todo lo de login
TEST_ENV=qa pytest -s -m "login and smoke"    # combinaciones
```

Los tags usados en `-m` deben estar registrados en `pytest.ini`.

Para exploración, sin modo estricto:

```bash
TEST_ENV=qa ROUTER_STRICT=false pytest -s -m login
```

## Manejo de fallos

Un step que no puede completarse deja el escenario como `FAILED`, y pytest continúa con los demás (no se usa `-x` ni `--maxfail=1`):

```text
Login usuario A                     PASSED
Transferencia cuenta inexistente    FAILED
Login usuario B                     PASSED

2 passed, 1 failed
```

El error se registra con el motivo legible para QA, el step que falló, la excepción técnica, el screenshot, el tiempo y la ruta de resolución. Un step rechazado por el modo estricto se reporta con su propio motivo (`sin_regla`).

## Evidencia

Cada corrida genera:

```text
evidencia/<fecha_hora>/
├── index.html                  informe agrupado por .feature
├── resumen.json                lo mismo en JSON, con conteos por feature y por ruta
├── login/
│   └── <escenario>/NN_<estado>_<paso>.png
└── login-empresa/
    └── <escenario>/NN_<estado>_<paso>.png
```

- Cada escenario tiene su propia carpeta, aunque dos features tengan escenarios con el mismo nombre. En un `Esquema del escenario`, cada ejemplo tiene la suya.
- La columna **Ruta** indica cómo se resolvió cada step (`deterministico`, `semantico`, `agentic`, `sin_regla`) y el encabezado resume cuántos hubo de cada tipo.

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

Al actualizar Skyvern, verifica también que `click()` y `fill()` sigan sin consultar al LLM cuando reciben solo un selector: la garantía del estilo por selector depende de ese comportamiento.