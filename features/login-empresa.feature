# language: es
@login-empresa
Característica: Acceso a banca en línea empresarial con selección de operador
  Como cliente empresarial del banco
  Quiero autenticarme primero con mi usuario y luego con mi contraseña
  Para consultar mi posición consolidada

  Antecedentes:
    Dado que abro la banca en línea

  @regression
  Escenario: Login empresarial exitoso muestra la posición consolidada del operador
    Dado que uso el perfil de prueba "smoke_login_empresa"
    Cuando ingreso la variable "username" en "campo Username"
    Y hago click en "botón Continue"
    Entonces hay un campo de texto password para escribir la contraseña
    Cuando ingreso la variable "password" en "campo Password"
    Y hago click en "botón Sign in"
    Entonces se muestra la seleccion de operador
    Cuando hago click en "operador Coca Cola"
    Entonces se muestra la posicion consolidada con 2 Accounts y 1 CreditCards
    Cuando hago click en "View summary de la card CUENTA PRINCIPAL terminada en 000001"
    Entonces espero a que se muestre la pantalla Product Summary
