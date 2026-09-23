# language: es
@login
Característica: Acceso a banca en línea con login de dos pasos
  Como cliente del banco
  Quiero autenticarme primero con mi usuario y luego con mi contraseña
  Para consultar mi posición consolidada

  Antecedentes:
    Dado que abro la banca en línea

  @smoke
  Escenario: Login exitoso muestra la posición consolidada
    Dado que uso el perfil de prueba "smoke_login_personal"
    Cuando ingreso el usuario en el campo username
    Y hago click en el boton continue
    Entonces hay un campo de texto password para escribir la contraseña
    Cuando ingreso la contraseña en el campo password
    Y hago click en el boton Sign in
    Entonces se muestra la posicion consolidada con 2 Accounts y 1 CreditCards
    Cuando hago click en "View summary" de la card "CUENTA PRINCIPAL" terminada en 000001
    Entonces espero a que se muestre la pantalla Product Summary
