# Requisitos - Deteccao de marcha no sistema de bordo

Este documento define a logica recomendada para inferir e exibir a marcha atual do
veiculo a partir dos dados OBD ja coletados pelo sistema de bordo.

Veiculo de referencia:

- Citroen C3 Picasso 2013 1.5 Flex
- Cambio manual de 5 marchas
- Tracao dianteira

## Objetivo

Identificar a marcha provavel durante a conducao e mostrar essa informacao na
tela de bordo, evitando indicacoes falsas durante:

- carro parado
- embreagem pressionada
- cambio em neutro
- desaceleracao com transmissao desacoplada
- leituras OBD antigas ou inconsistentes
- baixissima velocidade, onde `RPM / km/h` fica instavel

## Entradas

A maquina de estados deve usar os seguintes campos por amostra:

- `direct.rpm`
- `direct.speed_kmh`
- `metadata.dynamic_stale`
- `metadata.dynamic_stale_age_s`
- `inferred.engine_on`, quando disponivel
- timestamp da amostra, preferencialmente `time_context.sample_time`

Campos opcionais para melhorar confianca:

- `direct.throttle_pct`
- `direct.engine_load_pct`
- `direct.fuel_system_status_1`

## Conceitos

### Razao de marcha

A base da inferencia e:

```text
ratio = direct.rpm / direct.speed_kmh
```

Essa razao representa quantos RPM o motor esta girando para cada `1 km/h`.
Quando a embreagem esta acoplada, a razao tende a ficar em faixas estaveis para
cada marcha.

Quando a embreagem esta pressionada, o cambio esta em neutro ou o carro esta
rodando desacoplado, a razao cai para valores muito baixos, normalmente perto da
lenta do motor dividida pela velocidade.

### Faixas iniciais

As faixas abaixo foram derivadas das sessoes JSONL em `example_jsonl/`.

```text
ratio < 24        => desacoplado: neutro, embreagem ou coasting
24 <= ratio < 31  => desacoplado provavel; nao classificar como 6a
31 <= ratio < 39  => 5a marcha
39 <= ratio < 50  => 4a marcha
50 <= ratio < 75  => 3a marcha
75 <= ratio < 120 => 2a marcha
ratio >= 120      => 1a marcha
```

Observacao: o carro de referencia tem 5 marchas. Portanto, valores na faixa
`24..31` nao devem ser tratados como 6a marcha.

## Estados

A maquina de estados deve manter um dos estados abaixo.

### `OFF`

Motor desligado ou RPM invalido.

Condicoes de entrada:

- `rpm <= 0`
- ou `inferred.engine_on == false`
- ou `rpm < 400` por pelo menos uma amostra valida

Saida exibida:

- sem marcha
- opcionalmente `--`

### `STOPPED`

Motor ligado, carro parado ou em velocidade baixa demais para inferencia.

Condicoes de entrada:

- `rpm >= 400`
- e `speed_kmh < 8`

Saida exibida:

- `N` se a UI ja usa neutro como estado visual
- ou `--` se a UI preferir nao afirmar neutro sem sensor dedicado

### `UNKNOWN`

Leitura insuficiente, stale ou inconsistente.

Condicoes de entrada:

- `metadata.dynamic_stale == true`
- ou `metadata.dynamic_stale_age_s > 1.5`
- ou `speed_kmh` ausente
- ou `rpm` ausente
- ou `speed_kmh < 0`
- ou `rpm < 0`

Saida exibida:

- manter a ultima marcha confirmada por ate `2.0s`, com confianca baixa
- depois exibir `--`

### `DISENGAGED`

Transmissao provavelmente desacoplada: embreagem pressionada, neutro ou carro
rodando com motor em lenta.

Condicoes de entrada:

- `speed_kmh >= 8`
- `rpm >= 400`
- `ratio < 31`

Saida exibida:

- `N`
- ou icone/texto curto de neutro, conforme padrao da UI

Observacao: se `ratio` estiver entre `24` e `31`, ainda assim o requisito e
classificar como `DISENGAGED`, porque o veiculo nao possui 6a marcha.

### `IN_GEAR`

Transmissao acoplada e marcha inferida com base em `ratio`.

Subestados:

- `GEAR_1`
- `GEAR_2`
- `GEAR_3`
- `GEAR_4`
- `GEAR_5`

Saida exibida:

- `1`, `2`, `3`, `4` ou `5`

## Classificacao instantanea

Para cada amostra valida, calcular uma classificacao candidata:

```text
se rpm < 400 ou engine_on == false:
  candidato = OFF

senao se dynamic_stale == true ou dynamic_stale_age_s > 1.5:
  candidato = UNKNOWN

senao se speed_kmh < 8:
  candidato = STOPPED

senao:
  ratio = rpm / speed_kmh

  se ratio < 31:
    candidato = DISENGAGED
  senao se ratio < 39:
    candidato = GEAR_5
  senao se ratio < 50:
    candidato = GEAR_4
  senao se ratio < 75:
    candidato = GEAR_3
  senao se ratio < 120:
    candidato = GEAR_2
  senao:
    candidato = GEAR_1
```

## Estabilizacao

A classificacao instantanea nao deve ser exibida diretamente. O sistema deve
usar confirmacao temporal para evitar flicker.

### Confirmacao de marcha

Uma nova marcha deve substituir a marcha exibida somente quando:

- a mesma marcha candidata aparece em pelo menos `2` amostras consecutivas; ou
- a mesma marcha candidata permanece por pelo menos `0.8s`

Usar o criterio que acontecer primeiro.

Exemplo:

```text
GEAR_3 confirmado
amostra 1: candidato GEAR_4
amostra 2: candidato GEAR_4
estado exibido passa para GEAR_4
```

### Saida rapida para desacoplado

O estado `DISENGAGED` pode ser confirmado mais rapido que uma troca normal.

Confirmar `DISENGAGED` quando:

- `ratio < 24` em uma amostra valida; ou
- `ratio < 31` por `2` amostras consecutivas

Motivo: quando a embreagem e pressionada, o RPM pode cair rapidamente para perto
da lenta, e manter a marcha anterior por muito tempo fica visualmente incorreto.

### Retencao durante leitura desconhecida

Se o candidato for `UNKNOWN`, nao trocar imediatamente a exibicao para `--`.

Regras:

- se havia uma marcha confirmada nos ultimos `2.0s`, manter a marcha exibida
  com confianca baixa
- se `UNKNOWN` durar mais de `2.0s`, exibir `--`
- nao confirmar nova marcha a partir de amostras stale

## Histerese

Para reduzir oscilacao perto das fronteiras, usar margem de histerese de `2.0`
pontos de ratio ao permanecer na marcha atual.

Exemplo para `GEAR_3`:

- faixa normal de entrada: `50 <= ratio < 75`
- enquanto `GEAR_3` ja estiver confirmado, aceitar `48 <= ratio < 77`

Tabela com histerese:

```text
Estado atual GEAR_1: manter enquanto ratio >= 118
Estado atual GEAR_2: manter enquanto 73 <= ratio < 122
Estado atual GEAR_3: manter enquanto 48 <= ratio < 77
Estado atual GEAR_4: manter enquanto 37 <= ratio < 52
Estado atual GEAR_5: manter enquanto 29 <= ratio < 41
DISENGAGED: manter enquanto ratio < 33
```

A histerese deve ser aplicada somente depois que um estado ja esta confirmado.
A classificacao inicial continua usando as faixas principais.

## Confianca

Cada saida deve incluir uma confianca simples para a UI e para debug.

Valores recomendados:

- `high`: marcha confirmada por estabilidade e leitura nao stale
- `medium`: marcha recem-confirmada ou proxima de fronteira
- `low`: ultima marcha mantida durante `UNKNOWN`
- `none`: `OFF`, `STOPPED` ou dados invalidos

### Criterios sugeridos

`high`:

- estado `IN_GEAR`
- pelo menos `2` amostras consecutivas no mesmo estado
- `dynamic_stale == false`
- distancia ate a fronteira mais proxima >= `3.0` pontos de ratio

`medium`:

- estado `IN_GEAR`
- confirmado, mas perto de fronteira
- ou confirmado ha menos de `1.0s`

`low`:

- estado mantido por retencao durante `UNKNOWN`

`none`:

- `OFF`
- `STOPPED`
- `DISENGAGED`
- `UNKNOWN` sem marcha recente

## Saida esperada

A inferencia deve produzir um objeto ou estrutura equivalente:

```json
{
  "state": "IN_GEAR",
  "gear": 3,
  "ratio": 56.1,
  "confidence": "high",
  "display": "3",
  "reason": "ratio_in_gear_band"
}
```

Exemplos:

```json
{
  "state": "DISENGAGED",
  "gear": null,
  "ratio": 22.7,
  "confidence": "none",
  "display": "N",
  "reason": "ratio_below_engaged_threshold"
}
```

```json
{
  "state": "UNKNOWN",
  "gear": 4,
  "ratio": null,
  "confidence": "low",
  "display": "4",
  "reason": "stale_sample_retaining_last_confirmed_gear"
}
```

## Requisitos de UI

Na tela de bordo:

- mostrar apenas `1`, `2`, `3`, `4`, `5`, `N` ou `--`
- nao mostrar valores de ratio na tela principal
- usar `--` para motor desligado, dados invalidos ou desconhecido persistente
- usar `N` para `DISENGAGED`
- se existir tela de debug, mostrar `ratio`, `state`, `confidence` e `reason`

## Requisitos de logging

Quando a inferencia for gravada junto ao datalog, adicionar campos em
`inferred`:

```json
{
  "gear_state": "IN_GEAR",
  "gear": 3,
  "gear_ratio": 56.1,
  "gear_confidence": "high",
  "gear_reason": "ratio_in_gear_band"
}
```

Para compatibilidade, `gear` deve ser `null` quando nao houver marcha confirmada.

## Casos de teste minimos

### Motor desligado

Entrada:

```text
rpm = 0
speed_kmh = 0
```

Resultado:

```text
state = OFF
display = --
```

### Carro parado com motor ligado

Entrada:

```text
rpm = 800
speed_kmh = 0
```

Resultado:

```text
state = STOPPED
display = -- ou N, conforme decisao da UI
```

### Terceira marcha

Entrada:

```text
rpm = 2240
speed_kmh = 40
ratio = 56.0
```

Resultado:

```text
state = IN_GEAR
gear = 3
display = 3
```

### Quinta marcha

Entrada:

```text
rpm = 3330
speed_kmh = 100
ratio = 33.3
```

Resultado:

```text
state = IN_GEAR
gear = 5
display = 5
```

### Neutro ou embreagem em movimento

Entrada:

```text
rpm = 820
speed_kmh = 80
ratio = 10.25
```

Resultado:

```text
state = DISENGAGED
gear = null
display = N
```

### Faixa que antes poderia parecer 6a

Entrada:

```text
rpm = 900
speed_kmh = 32
ratio = 28.1
```

Resultado:

```text
state = DISENGAGED
gear = null
display = N
```

## Parametros ajustaveis

Implementar estes valores como constantes configuraveis:

```text
MIN_ENGINE_RPM = 400
MIN_SPEED_FOR_GEAR_KMH = 8
STALE_MAX_AGE_S = 1.5
UNKNOWN_HOLD_S = 2.0
GEAR_CONFIRM_SAMPLES = 2
GEAR_CONFIRM_TIME_S = 0.8
HYSTERESIS_RATIO = 2.0
DISENGAGED_RATIO = 31.0
FAST_DISENGAGED_RATIO = 24.0
```

## Criterios de aceitacao

A implementacao sera considerada correta quando:

- nao exibir 6a marcha
- classificar `ratio < 31` como `DISENGAGED`
- identificar corretamente as 5 marchas usando as faixas definidas
- nao oscilar rapidamente entre duas marchas vizinhas
- nao trocar marcha usando amostras stale
- manter a ultima marcha por curto periodo durante perda temporaria de dados
- gerar uma saida simples para a UI e uma saida detalhada para debug/logging
