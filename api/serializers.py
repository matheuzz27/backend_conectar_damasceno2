# api/serializers.py

from rest_framework import serializers
from .models import Cliente, Produto, Venda, ItemVenda, PagamentoVenda, Orcamento, ItemOrcamento, PagamentoRecebido
from django.contrib.auth.models import User

# -------------------------------------------------
# SERIALIZERS BÁSICOS
# -------------------------------------------------

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ['id', 'username', 'password', 'first_name', 'is_staff']

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', '')
        )
        return user

    def update(self, instance, validated_data):
        instance.username = validated_data.get('username', instance.username)
        instance.first_name = validated_data.get('first_name', instance.first_name)
        password = validated_data.get('password')
        if password:
            instance.set_password(password)
        instance.save()
        return instance
    
class ClienteSerializer(serializers.ModelSerializer):
    # OTIMIZAÇÃO: Este campo agora vem pronto da View (annotate)
    # Não precisa mais de métodos complexos aqui.
    saldo_devedor = serializers.DecimalField(
        source='saldo_calculado', # Pega o valor calculado no banco
        max_digits=10, 
        decimal_places=2, 
        read_only=True
    )

    class Meta:
        model = Cliente
        fields = ['id', 'nome', 'telefone', 'endereco', 'saldo_devedor']
            
class ProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Produto
        fields = '__all__'

class PagamentoRecebidoSerializer(serializers.ModelSerializer):
    clienteNome = serializers.CharField(source='cliente.nome', read_only=True)
    class Meta:
        model = PagamentoRecebido
        fields = '__all__'

# -------------------------------------------------
# SERIALIZERS DE VENDA
# -------------------------------------------------

class ItemVendaSerializer(serializers.ModelSerializer):
    valorUnitario = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    valorFinal = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    preco_tab_original = serializers.DecimalField(source='produto.precoVenda', max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = ItemVenda
        exclude = ['venda']
        read_only_fields = ['nome', 'precoCompra'] 

class PagamentoVendaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PagamentoVenda
        exclude = ['venda']

class VendaSerializer(serializers.ModelSerializer):
    itens = ItemVendaSerializer(many=True)
    pagamento = PagamentoVendaSerializer(many=True)
    
    clienteNome = serializers.CharField(source='cliente.nome', read_only=True)
    vendedorNome = serializers.CharField(source='vendedor.first_name', read_only=True)

    class Meta:
        model = Venda
        fields = '__all__'
        read_only_fields = ['subtotal', 'total'] 
    
    def create(self, validated_data):
        itens_data = validated_data.pop('itens')
        pagamentos_data = validated_data.pop('pagamento')
        
        # 1. Cria Venda
        validated_data['subtotal'] = validated_data.get('subtotal', 0)
        validated_data['total'] = validated_data.get('total', 0)
        venda = Venda.objects.create(**validated_data)

        total_calculado_venda = 0

        # 2. Processa Itens
        for item_data in itens_data:
            produto = item_data['produto']
            quantidade = item_data['quantidade']
            
            # Lógica de Preço
            if 'valorUnitario' in item_data and item_data['valorUnitario'] is not None:
                preco_unitario = item_data['valorUnitario']
            else:
                preco_unitario = produto.precoVenda

            if 'valorFinal' in item_data and item_data['valorFinal'] is not None:
                valor_final_item = item_data['valorFinal']
            else:
                valor_final_item = preco_unitario * quantidade

            total_calculado_venda += valor_final_item

            ItemVenda.objects.create(
                venda=venda,
                produto=produto,
                quantidade=quantidade,
                valorUnitario=preco_unitario,
                valorFinal=valor_final_item,
                precoCompra=produto.precoCompra,
                nome=produto.nome
            )
            
        # 3. Processa Pagamentos (Aqui criamos as parcelas que serão somadas no saldo)
        for pagamento_data in pagamentos_data:
            PagamentoVenda.objects.create(venda=venda, **pagamento_data)

        # 4. Atualiza Totais
        venda.subtotal = total_calculado_venda
        venda.total = total_calculado_venda - venda.desconto
        venda.save()

        return venda

# -------------------------------------------------
# SERIALIZERS DE ORÇAMENTO
# -------------------------------------------------

class ItemOrcamentoSerializer(serializers.ModelSerializer):
    valorUnitario = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    valorFinal = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)

    class Meta:
        model = ItemOrcamento
        exclude = ['orcamento']
        read_only_fields = ['nome', 'precoCompra']

class OrcamentoSerializer(serializers.ModelSerializer):
    itens = ItemOrcamentoSerializer(many=True)
    clienteNome = serializers.CharField(source='cliente.nome', read_only=True)
    vendedorNome = serializers.CharField(source='vendedor.first_name', read_only=True)

    class Meta:
        model = Orcamento
        fields = '__all__'
        read_only_fields = ['total']
    
    def create(self, validated_data):
        itens_data = validated_data.pop('itens')
        validated_data['total'] = 0
        orcamento = Orcamento.objects.create(**validated_data)
        
        total_calc = 0
        
        for item_data in itens_data:
            produto = item_data['produto']
            quantidade = item_data['quantidade']
            
            valor_enviado = item_data.get('valorUnitario')
            if valor_enviado is not None and float(valor_enviado) > 0:
                preco_unitario = valor_enviado
            else:
                preco_unitario = produto.precoVenda

            total_enviado = item_data.get('valorFinal')
            if total_enviado is not None and float(total_enviado) > 0:
                valor_final_item = total_enviado
            else:
                valor_final_item = preco_unitario * quantidade

            total_calc += valor_final_item
            
            ItemOrcamento.objects.create(
                orcamento=orcamento,
                produto=produto,
                quantidade=quantidade,
                valorUnitario=preco_unitario,
                valorFinal=valor_final_item,
                precoCompra=produto.precoCompra,
                nome=produto.nome
            )
        
        orcamento.total = total_calc
        orcamento.save()
        return orcamento

# -------------------------------------------------
# RELATÓRIOS
# -------------------------------------------------
class RelatorioDevedorSerializer(serializers.ModelSerializer):
    saldo_devedor_atual = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    divida_bruta = serializers.DecimalField(source='divida_bruta_com_juros', max_digits=10, decimal_places=2, read_only=True)
    total_pago = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Cliente
        fields = ['id', 'nome', 'telefone', 'endereco', 'saldo_devedor_atual', 'divida_bruta', 'total_pago']