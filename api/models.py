# api/models.py
from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date

# --- LISTAS DE OPÇÕES ---
OPCOES_PAGAMENTO_VENDA = [
    ('DINHEIRO', 'Dinheiro'),
    ('PIX', 'Pix'),
    ('CARTÃO', 'Cartão'),
    ('PRAZO', 'A Prazo (Fiado)'),
]

OPCOES_PAGAMENTO_RECEBIDO = [
    ('DINHEIRO', 'Dinheiro'),
    ('PIX', 'Pix'),
    ('CARTÃO', 'Cartão'),
]

# -------------------------------------------------
# MODELOS
# -------------------------------------------------

class Cliente(models.Model):
    nome = models.CharField(max_length=255, unique=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    endereco = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.nome

class Produto(models.Model):
    nome = models.CharField(max_length=255, unique=True)
    precoCompra = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    precoVenda = models.DecimalField(max_digits=10, decimal_places=2)
    tem_preco_prazo = models.BooleanField(default=False, verbose_name="Tem Preço a Prazo?")
    preco_prazo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Preço a Prazo")

    def __str__(self):
        return self.nome

class Venda(models.Model):
    cliente = models.ForeignKey(Cliente, related_name='vendas', on_delete=models.PROTECT)
    vendedor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    data = models.DateTimeField(auto_now_add=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    desconto = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"Venda #{self.id} - {self.cliente.nome}"

class ItemVenda(models.Model):
    venda = models.ForeignKey(Venda, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    nome = models.CharField(max_length=255)
    quantidade = models.DecimalField(max_digits=10, decimal_places=3)
    valorUnitario = models.DecimalField(max_digits=10, decimal_places=2)
    valorFinal = models.DecimalField(max_digits=10, decimal_places=2)
    precoCompra = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantidade} x {self.nome}"

class PagamentoVenda(models.Model):
    venda = models.ForeignKey(Venda, related_name='pagamento', on_delete=models.CASCADE)
    metodo = models.CharField(max_length=50, choices=OPCOES_PAGAMENTO_VENDA, default='DINHEIRO')
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, default='PAGO') 

    # 📈 INTELIGÊNCIA: JUROS AUTOMÁTICOS DE 3% A CADA 30 DIAS
    @property
    def valor_com_juros(self):
        if self.metodo != 'PRAZO' or self.status != 'PENDENTE':
            return self.valor
        
        dias_atraso = (date.today() - self.venda.data.date()).days
        meses_atrasados = dias_atraso // 30 # Divide por 30 ignorando o resto (ex: 45 dias = 1 mês)
        
        if meses_atrasados > 0:
            juros = Decimal('0.03') * meses_atrasados
            valor_atualizado = self.valor * (Decimal('1.00') + juros)
            return round(valor_atualizado, 2)
        
        return self.valor

class Orcamento(models.Model):
    cliente = models.ForeignKey(Cliente, related_name='orcamentos', on_delete=models.PROTECT)
    vendedor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    data = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, default='PENDENTE')

class ItemOrcamento(models.Model):
    orcamento = models.ForeignKey(Orcamento, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    nome = models.CharField(max_length=255)
    quantidade = models.DecimalField(max_digits=10, decimal_places=3)
    valorUnitario = models.DecimalField(max_digits=10, decimal_places=2)
    valorFinal = models.DecimalField(max_digits=10, decimal_places=2)
    precoCompra = models.DecimalField(max_digits=10, decimal_places=2)

class PagamentoRecebido(models.Model):
    cliente = models.ForeignKey(Cliente, related_name='pagamentos_recebidos', on_delete=models.PROTECT)
    data = models.DateTimeField(auto_now_add=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    metodo = models.CharField(max_length=50, choices=OPCOES_PAGAMENTO_RECEBIDO, default='DINHEIRO')

    def __str__(self):
        return f"Pagamento de {self.cliente.nome} - R${self.valor}"