# api/utils.py
from decimal import Decimal
from datetime import date

def calcular_juros(data_venda, valor_original):
    """
    Calcula juros de 1.5% a cada 15 dias de atraso.
    """
    if not data_venda or not valor_original:
        return Decimal('0.00')
    
    # Garante que valor_original é Decimal
    valor = Decimal(str(valor_original))
    
    hoje = date.today()
    # Pega apenas a data da venda (sem hora)
    data_venda_date = data_venda.date()
    
    dias_atraso = (hoje - data_venda_date).days
    
    if dias_atraso < 15:
        return Decimal('0.00')
    
    # Divisão inteira para saber quantos períodos de 15 dias passaram
    periodos = dias_atraso // 15
    taxa = Decimal('0.015')
    
    juros = valor * taxa * periodos
    return juros.quantize(Decimal('0.01')) # Arredonda para 2 casas