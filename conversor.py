import requests


def buscar_taxas(moeda_base):
    url = f"https://open.er-api.com/v6/latest/{moeda_base}"
    response = requests.get(url)
    dados = response.json()
    return dados


def converter(valor, moeda_origem, moeda_destino):
    dados = buscar_taxas(moeda_origem)
    taxas = dados["rates"]

    if moeda_destino not in taxas:
        print(f"Moeda {moeda_destino} não encontrada.")
        return

    resultado = valor * taxas[moeda_destino]
    data_atualizacao = dados["time_last_update_utc"]

    print(f"\n{valor} {moeda_origem} = {resultado:.2f} {moeda_destino}")
    print(f"Taxa atualizada em: {data_atualizacao}")


def main():
    print("=== Conversor de Moedas ===")
    print("Digite 'sair' para encerrar.\n")

    while True:
        moeda_origem = input("Moeda de origem (ex: USD, BRL, EUR): ").upper()
        if moeda_origem == "SAIR":
            break

        moeda_destino = input("Moeda de destino (ex: USD, BRL, EUR): ").upper()
        if moeda_destino == "SAIR":
            break

        try:
            valor = float(input("Valor a converter: "))
            converter(valor, moeda_origem, moeda_destino)
        except ValueError:
            print("Valor inválido. Digite um número.")

        print()


main()
