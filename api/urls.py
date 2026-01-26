# api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UserViewSet, 
    ClienteViewSet, 
    ProdutoViewSet, 
    VendaViewSet, 
    OrcamentoViewSet, 
    PagamentoRecebidoViewSet,
    RelatorioDevedoresView,
    DashboardView
)

# Cria o Roteador Automático
router = DefaultRouter()
router.register(r'usuarios', UserViewSet)
router.register(r'clientes', ClienteViewSet)
router.register(r'produtos', ProdutoViewSet)
router.register(r'vendas', VendaViewSet)
router.register(r'orcamentos', OrcamentoViewSet)

# CORREÇÃO AQUI: O frontend espera "pagamentos-recebidos" (com hífen), não apenas "pagamentos"
router.register(r'pagamentos-recebidos', PagamentoRecebidoViewSet) 

urlpatterns = [
    # --- ROTA MANUAL DE SEGURANÇA (PRIORIDADE ALTA) ---
    # Isso garante que o Django não confunda o comando com um ID de cliente
    path('clientes/receber_pagamento/', ClienteViewSet.as_view({'post': 'receber_pagamento'}), name='receber-pagamento'),

    # Rotas Automáticas do CRUD
    path('', include(router.urls)),

    # Rotas Manuais (Relatórios e Dashboard)
    path('relatorios/devedores/', RelatorioDevedoresView.as_view(), name='relatorio-devedores'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
]