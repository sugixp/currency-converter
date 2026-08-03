# Currency Converter 💱

A command-line tool that converts currencies in real time using the Open Exchange Rates API.

## Features

- Real-time exchange rates
- Supports 150+ currencies (USD, BRL, EUR, GBP and more)
- Multiple conversions in a single session
- Displays the last update timestamp for each rate

## Technologies

- Python 3
- Requests library
- Open Exchange Rates API

## How to run

1. Clone the repository

```bash
git clone https://github.com/sugixp/currency-converter.git
cd currency-converter
```

2. Install dependencies

```bash
pip install -r requirements.txt
```

3. Run the program

```bash
python conversor.py
```

## Example

```
=== Conversor de Moedas ===
Moeda de origem: USD
Moeda de destino: BRL
Valor: 59

59.0 USD = 299.13 BRL
Taxa atualizada em: Sat, 02 Aug 2026 00:00:01 +0000
```
