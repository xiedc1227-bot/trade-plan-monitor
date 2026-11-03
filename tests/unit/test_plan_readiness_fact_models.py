"""Facts preserve native outcomes and old readiness bytes without granting authority."""

import hashlib
import json
from dataclasses import asdict
from datetime import date, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.unit.test_plan_readiness import NOW, observation, rule, snapshot

from trade_plan_monitor.notifications.channels import ChannelErrorCode, DeliveryChannel
from trade_plan_monitor.notifications.dispatcher import DeliveryAttemptRecord, DeliveryAttemptStatus
from trade_plan_monitor.notifications.recovery_eligibility import RecoveryDeliveryStatus
from trade_plan_monitor.web import plan_readiness_models as models

# Frozen from the actual a6 production fixture before this contract extension.
A6_JSON = (
    '{"contractVersion":"plan-monitor-readiness-v1","authorityGranted":false,"snapshot":{"'
    'computedAt":"2026-09-14T10:05:15+08:00","context":{"planVersionId":"c77a7169-91d3-40b'
    '6-8e73-7676860c2d6e","contentHash":"c0b7be911e72d2a3a826e58c8ee04e77da25ea5a66e59fc13'
    '3f7d4c5ffcb0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1e48d96fe1133518e21c0'
    'cda12b373d","coverageHash":"2a4aecea2009d6f9a68a08070a85c41e53f9d4dfd4dca464173fac44d'
    '026f0ce","reviewReceiptHash":"f3386f13ca1f54275825c00323373663200e211564c5df9938beb59'
    '1e3a7390b","activationRevision":1,"runtimeGeneration":"04bd1e22-ff58-4743-a479-b80bea'
    'a653c1","inventoryRevision":1,"bookRevision":null},"scope":"MIXED","axes":[{"axis":"S'
    'OURCE_COVERAGE","state":"PASS","reason":null,"observation":{"context":{"planVersionId'
    '":"c77a7169-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0b7be911e72d2a3a826e58c8ee04'
    'e77da25ea5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1'
    'e48d96fe1133518e21c0cda12b373d","coverageHash":"2a4aecea2009d6f9a68a08070a85c41e53f9d'
    '4dfd4dca464173fac44d026f0ce","reviewReceiptHash":"f3386f13ca1f54275825c00323373663200'
    'e211564c5df9938beb591e3a7390b","activationRevision":1,"runtimeGeneration":"04bd1e22-f'
    'f58-4743-a479-b80beaa653c1","inventoryRevision":1,"bookRevision":null},"availability"'
    ':"CURRENT","observedAt":"2026-09-14T10:05:15+08:00","asOf":null,"expiresAt":"2026-09-'
    '14T10:05:45+08:00","evidenceRefs":["plan:c77a7169-91d3-40b6-8e73-7676860c2d6e","cover'
    'age:e850916ca9817aa53c4d5d9998529fc311a72288f1f48473274ce32bd9769392"],"provider":nul'
    'l,"priceBasis":null,"formulaVersion":null,"calendarReference":null}},{"axis":"REVIEW_'
    'ACTIVATION","state":"PASS","reason":null,"observation":{"context":{"planVersionId":"c'
    '77a7169-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0b7be911e72d2a3a826e58c8ee04e77d'
    'a25ea5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1e48d'
    '96fe1133518e21c0cda12b373d","coverageHash":"2a4aecea2009d6f9a68a08070a85c41e53f9d4dfd'
    '4dca464173fac44d026f0ce","reviewReceiptHash":"f3386f13ca1f54275825c00323373663200e211'
    '564c5df9938beb591e3a7390b","activationRevision":1,"runtimeGeneration":"04bd1e22-ff58-'
    '4743-a479-b80beaa653c1","inventoryRevision":1,"bookRevision":null},"availability":"CU'
    'RRENT","observedAt":"2026-09-14T10:05:15+08:00","asOf":null,"expiresAt":"2026-09-14T1'
    '0:05:45+08:00","evidenceRefs":["plan:c77a7169-91d3-40b6-8e73-7676860c2d6e","coverage:'
    'e850916ca9817aa53c4d5d9998529fc311a72288f1f48473274ce32bd9769392"],"provider":null,"p'
    'riceBasis":null,"formulaVersion":null,"calendarReference":null}},{"axis":"RUNTIME_OWN'
    'ERSHIP","state":"PASS","reason":null,"observation":{"context":{"planVersionId":"c77a7'
    '169-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0b7be911e72d2a3a826e58c8ee04e77da25e'
    'a5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1e48d96fe'
    '1133518e21c0cda12b373d","coverageHash":"2a4aecea2009d6f9a68a08070a85c41e53f9d4dfd4dca'
    '464173fac44d026f0ce","reviewReceiptHash":"f3386f13ca1f54275825c00323373663200e211564c'
    '5df9938beb591e3a7390b","activationRevision":1,"runtimeGeneration":"04bd1e22-ff58-4743'
    '-a479-b80beaa653c1","inventoryRevision":1,"bookRevision":null},"availability":"CURREN'
    'T","observedAt":"2026-09-14T10:05:15+08:00","asOf":null,"expiresAt":"2026-09-14T10:05'
    ':45+08:00","evidenceRefs":["runtime:04bd1e22-ff58-4743-a479-b80beaa653c1"],"provider"'
    ':null,"priceBasis":null,"formulaVersion":null,"calendarReference":null}},{"axis":"DAT'
    'A_EVALUATION","state":"PASS","reason":null,"observation":{"context":{"planVersionId":'
    '"c77a7169-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0b7be911e72d2a3a826e58c8ee04e7'
    '7da25ea5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1e4'
    '8d96fe1133518e21c0cda12b373d","coverageHash":"2a4aecea2009d6f9a68a08070a85c41e53f9d4d'
    'fd4dca464173fac44d026f0ce","reviewReceiptHash":"f3386f13ca1f54275825c00323373663200e2'
    '11564c5df9938beb591e3a7390b","activationRevision":1,"runtimeGeneration":"04bd1e22-ff5'
    '8-4743-a479-b80beaa653c1","inventoryRevision":1,"bookRevision":null},"availability":"'
    'CURRENT","observedAt":"2026-09-14T10:05:15+08:00","asOf":"2026-09-14T10:05:15+08:00",'
    '"expiresAt":"2026-09-14T10:05:45+08:00","evidenceRefs":["a73b1797bb1a1d4ef21a37c2d510'
    '305432ac52805f7bc383b571d272f96e7811"],"provider":null,"priceBasis":null,"formulaVers'
    'ion":null,"calendarReference":null}},{"axis":"INVENTORY_CAPITAL","state":"PASS","reas'
    'on":null,"observation":{"context":{"planVersionId":"c77a7169-91d3-40b6-8e73-7676860c2'
    'd6e","contentHash":"c0b7be911e72d2a3a826e58c8ee04e77da25ea5a66e59fc133f7d4c5ffcb0b71"'
    ',"sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1e48d96fe1133518e21c0cda12b373d","cov'
    'erageHash":"2a4aecea2009d6f9a68a08070a85c41e53f9d4dfd4dca464173fac44d026f0ce","review'
    'ReceiptHash":"f3386f13ca1f54275825c00323373663200e211564c5df9938beb591e3a7390b","acti'
    'vationRevision":1,"runtimeGeneration":"04bd1e22-ff58-4743-a479-b80beaa653c1","invento'
    'ryRevision":1,"bookRevision":null},"availability":"CURRENT","observedAt":"2026-09-14T'
    '10:05:15+08:00","asOf":null,"expiresAt":"2026-09-14T10:05:45+08:00","evidenceRefs":["'
    'inventory:1"],"provider":null,"priceBasis":null,"formulaVersion":null,"calendarRefere'
    'nce":null}},{"axis":"NOTIFICATION_DELIVERY","state":"UNKNOWN","reason":"DELIVERY_UNVE'
    'RIFIED","observation":null}],"rules":[{"ownerKind":"ORDINARY_RULE","ownerId":"low-buy'
    '","side":"BUY","requirements":{"inventory":true,"sellability":false,"quote":false,"si'
    'mulationBook":false,"costBasis":false,"fees":false,"economics":false},"expectedTarget'
    '":{"kind":"INTRADAY","bucket_end":"2026-09-14T10:05:00+08:00"},"evaluatedTarget":{"ki'
    'nd":"INTRADAY","bucket_end":"2026-09-14T10:05:00+08:00"},"evaluatedAt":"2026-09-14T10'
    ':05:15+08:00","observation":{"context":{"planVersionId":"c77a7169-91d3-40b6-8e73-7676'
    '860c2d6e","contentHash":"c0b7be911e72d2a3a826e58c8ee04e77da25ea5a66e59fc133f7d4c5ffcb'
    '0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1e48d96fe1133518e21c0cda12b373d"'
    ',"coverageHash":"2a4aecea2009d6f9a68a08070a85c41e53f9d4dfd4dca464173fac44d026f0ce","r'
    'eviewReceiptHash":"f3386f13ca1f54275825c00323373663200e211564c5df9938beb591e3a7390b",'
    '"activationRevision":1,"runtimeGeneration":"04bd1e22-ff58-4743-a479-b80beaa653c1","in'
    'ventoryRevision":1,"bookRevision":null},"availability":"CURRENT","observedAt":"2026-0'
    '9-14T10:05:15+08:00","asOf":"2026-09-14T10:05:15+08:00","expiresAt":"2026-09-14T10:05'
    ':45+08:00","evidenceRefs":["a73b1797bb1a1d4ef21a37c2d510305432ac52805f7bc383b571d272f'
    '96e7811"],"provider":null,"priceBasis":null,"formulaVersion":null,"calendarReference"'
    ':null},"rootOutcome":"SATISFIED","leaves":[{"conditionPath":"condition.conditions[0]"'
    ',"state":"CONDITION_TRUE","reason":null,"evidenceRefs":["a73b1797bb1a1d4ef21a37c2d510'
    '305432ac52805f7bc383b571d272f96e7811"]},{"conditionPath":"condition.conditions[1]","s'
    'tate":"CONDITION_TRUE","reason":null,"evidenceRefs":["a73b1797bb1a1d4ef21a37c2d510305'
    '432ac52805f7bc383b571d272f96e7811"]}],"expectedConfirmation":null,"execution":{"appro'
    'vedQuantity":100,"consumed":false,"executionWindow":"CURRENT_SESSION","windowState":"'
    'OPEN","eligible":true,"reason":null}},{"ownerKind":"ORDINARY_RULE","ownerId":"sell-10'
    '0","side":"SELL","requirements":{"inventory":true,"sellability":true,"quote":false,"s'
    'imulationBook":false,"costBasis":false,"fees":false,"economics":false},"expectedTarge'
    't":{"kind":"INTRADAY","bucket_end":"2026-09-14T10:05:00+08:00"},"evaluatedTarget":{"k'
    'ind":"INTRADAY","bucket_end":"2026-09-14T10:05:00+08:00"},"evaluatedAt":"2026-09-14T1'
    '0:05:15+08:00","observation":{"context":{"planVersionId":"c77a7169-91d3-40b6-8e73-767'
    '6860c2d6e","contentHash":"c0b7be911e72d2a3a826e58c8ee04e77da25ea5a66e59fc133f7d4c5ffc'
    'b0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1e48d96fe1133518e21c0cda12b373d'
    '","coverageHash":"2a4aecea2009d6f9a68a08070a85c41e53f9d4dfd4dca464173fac44d026f0ce","'
    'reviewReceiptHash":"f3386f13ca1f54275825c00323373663200e211564c5df9938beb591e3a7390b"'
    ',"activationRevision":1,"runtimeGeneration":"04bd1e22-ff58-4743-a479-b80beaa653c1","i'
    'nventoryRevision":1,"bookRevision":null},"availability":"CURRENT","observedAt":"2026-'
    '09-14T10:05:15+08:00","asOf":"2026-09-14T10:05:15+08:00","expiresAt":"2026-09-14T10:0'
    '5:45+08:00","evidenceRefs":["a73b1797bb1a1d4ef21a37c2d510305432ac52805f7bc383b571d272'
    'f96e7811"],"provider":null,"priceBasis":null,"formulaVersion":null,"calendarReference'
    '":null},"rootOutcome":"UNSATISFIED","leaves":[{"conditionPath":"condition","state":"C'
    'ONDITION_FALSE","reason":null,"evidenceRefs":["a73b1797bb1a1d4ef21a37c2d510305432ac52'
    '805f7bc383b571d272f96e7811"]}],"expectedConfirmation":null,"execution":{"approvedQuan'
    'tity":null,"consumed":null,"executionWindow":null,"windowState":"UNKNOWN","eligible":'
    'null,"reason":null}},{"ownerKind":"ALERT_RULE","ownerId":"risk-below-950","side":null'
    ',"requirements":{"inventory":false,"sellability":false,"quote":false,"simulationBook"'
    ':false,"costBasis":false,"fees":false,"economics":false},"expectedTarget":{"kind":"IN'
    'TRADAY","bucket_end":"2026-09-14T10:05:00+08:00"},"evaluatedTarget":{"kind":"INTRADAY'
    '","bucket_end":"2026-09-14T10:05:00+08:00"},"evaluatedAt":"2026-09-14T10:05:15+08:00"'
    ',"observation":{"context":{"planVersionId":"c77a7169-91d3-40b6-8e73-7676860c2d6e","co'
    'ntentHash":"c0b7be911e72d2a3a826e58c8ee04e77da25ea5a66e59fc133f7d4c5ffcb0b71","source'
    'Hash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1e48d96fe1133518e21c0cda12b373d","coverageHas'
    'h":"2a4aecea2009d6f9a68a08070a85c41e53f9d4dfd4dca464173fac44d026f0ce","reviewReceiptH'
    'ash":"f3386f13ca1f54275825c00323373663200e211564c5df9938beb591e3a7390b","activationRe'
    'vision":1,"runtimeGeneration":"04bd1e22-ff58-4743-a479-b80beaa653c1","inventoryRevisi'
    'on":1,"bookRevision":null},"availability":"CURRENT","observedAt":"2026-09-14T10:05:15'
    '+08:00","asOf":"2026-09-14T10:05:15+08:00","expiresAt":"2026-09-14T10:05:45+08:00","e'
    'videnceRefs":["a73b1797bb1a1d4ef21a37c2d510305432ac52805f7bc383b571d272f96e7811"],"pr'
    'ovider":null,"priceBasis":null,"formulaVersion":null,"calendarReference":null},"rootO'
    'utcome":"UNSATISFIED","leaves":[{"conditionPath":"condition","state":"CONDITION_FALSE'
    '","reason":null,"evidenceRefs":["a73b1797bb1a1d4ef21a37c2d510305432ac52805f7bc383b571'
    'd272f96e7811"]}],"expectedConfirmation":null,"execution":{"approvedQuantity":null,"co'
    'nsumed":null,"executionWindow":null,"windowState":"UNKNOWN","eligible":null,"reason":'
    'null}}]},"axes":[{"axis":"SOURCE_COVERAGE","state":"PASS","reason":null,"observation"'
    ':{"context":{"planVersionId":"c77a7169-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0'
    'b7be911e72d2a3a826e58c8ee04e77da25ea5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766c'
    'f9e8f4c8ca3f5a69436f1d7e1a1e48d96fe1133518e21c0cda12b373d","coverageHash":"2a4aecea20'
    '09d6f9a68a08070a85c41e53f9d4dfd4dca464173fac44d026f0ce","reviewReceiptHash":"f3386f13'
    'ca1f54275825c00323373663200e211564c5df9938beb591e3a7390b","activationRevision":1,"run'
    'timeGeneration":"04bd1e22-ff58-4743-a479-b80beaa653c1","inventoryRevision":1,"bookRev'
    'ision":null},"availability":"CURRENT","observedAt":"2026-09-14T10:05:15+08:00","asOf"'
    ':null,"expiresAt":"2026-09-14T10:05:45+08:00","evidenceRefs":["plan:c77a7169-91d3-40b'
    '6-8e73-7676860c2d6e","coverage:e850916ca9817aa53c4d5d9998529fc311a72288f1f48473274ce3'
    '2bd9769392"],"provider":null,"priceBasis":null,"formulaVersion":null,"calendarReferen'
    'ce":null}},{"axis":"REVIEW_ACTIVATION","state":"PASS","reason":null,"observation":{"c'
    'ontext":{"planVersionId":"c77a7169-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0b7be'
    '911e72d2a3a826e58c8ee04e77da25ea5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766cf9e8'
    'f4c8ca3f5a69436f1d7e1a1e48d96fe1133518e21c0cda12b373d","coverageHash":"2a4aecea2009d6'
    'f9a68a08070a85c41e53f9d4dfd4dca464173fac44d026f0ce","reviewReceiptHash":"f3386f13ca1f'
    '54275825c00323373663200e211564c5df9938beb591e3a7390b","activationRevision":1,"runtime'
    'Generation":"04bd1e22-ff58-4743-a479-b80beaa653c1","inventoryRevision":1,"bookRevisio'
    'n":null},"availability":"CURRENT","observedAt":"2026-09-14T10:05:15+08:00","asOf":nul'
    'l,"expiresAt":"2026-09-14T10:05:45+08:00","evidenceRefs":["plan:c77a7169-91d3-40b6-8e'
    '73-7676860c2d6e","coverage:e850916ca9817aa53c4d5d9998529fc311a72288f1f48473274ce32bd9'
    '769392"],"provider":null,"priceBasis":null,"formulaVersion":null,"calendarReference":'
    'null}},{"axis":"RUNTIME_OWNERSHIP","state":"PASS","reason":null,"observation":{"conte'
    'xt":{"planVersionId":"c77a7169-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0b7be911e'
    '72d2a3a826e58c8ee04e77da25ea5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766cf9e8f4c8'
    'ca3f5a69436f1d7e1a1e48d96fe1133518e21c0cda12b373d","coverageHash":"2a4aecea2009d6f9a6'
    '8a08070a85c41e53f9d4dfd4dca464173fac44d026f0ce","reviewReceiptHash":"f3386f13ca1f5427'
    '5825c00323373663200e211564c5df9938beb591e3a7390b","activationRevision":1,"runtimeGene'
    'ration":"04bd1e22-ff58-4743-a479-b80beaa653c1","inventoryRevision":1,"bookRevision":n'
    'ull},"availability":"CURRENT","observedAt":"2026-09-14T10:05:15+08:00","asOf":null,"e'
    'xpiresAt":"2026-09-14T10:05:45+08:00","evidenceRefs":["runtime:04bd1e22-ff58-4743-a47'
    '9-b80beaa653c1"],"provider":null,"priceBasis":null,"formulaVersion":null,"calendarRef'
    'erence":null}},{"axis":"DATA_EVALUATION","state":"PASS","reason":null,"observation":{'
    '"context":{"planVersionId":"c77a7169-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0b7'
    'be911e72d2a3a826e58c8ee04e77da25ea5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766cf9'
    'e8f4c8ca3f5a69436f1d7e1a1e48d96fe1133518e21c0cda12b373d","coverageHash":"2a4aecea2009'
    'd6f9a68a08070a85c41e53f9d4dfd4dca464173fac44d026f0ce","reviewReceiptHash":"f3386f13ca'
    '1f54275825c00323373663200e211564c5df9938beb591e3a7390b","activationRevision":1,"runti'
    'meGeneration":"04bd1e22-ff58-4743-a479-b80beaa653c1","inventoryRevision":1,"bookRevis'
    'ion":null},"availability":"CURRENT","observedAt":"2026-09-14T10:05:15+08:00","asOf":"'
    '2026-09-14T10:05:15+08:00","expiresAt":"2026-09-14T10:05:45+08:00","evidenceRefs":["a'
    '73b1797bb1a1d4ef21a37c2d510305432ac52805f7bc383b571d272f96e7811"],"provider":null,"pr'
    'iceBasis":null,"formulaVersion":null,"calendarReference":null}},{"axis":"INVENTORY_CA'
    'PITAL","state":"PASS","reason":null,"observation":{"context":{"planVersionId":"c77a71'
    '69-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0b7be911e72d2a3a826e58c8ee04e77da25ea'
    '5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1e48d96fe1'
    '133518e21c0cda12b373d","coverageHash":"2a4aecea2009d6f9a68a08070a85c41e53f9d4dfd4dca4'
    '64173fac44d026f0ce","reviewReceiptHash":"f3386f13ca1f54275825c00323373663200e211564c5'
    'df9938beb591e3a7390b","activationRevision":1,"runtimeGeneration":"04bd1e22-ff58-4743-'
    'a479-b80beaa653c1","inventoryRevision":1,"bookRevision":null},"availability":"CURRENT'
    '","observedAt":"2026-09-14T10:05:15+08:00","asOf":null,"expiresAt":"2026-09-14T10:05:'
    '45+08:00","evidenceRefs":["inventory:1"],"provider":null,"priceBasis":null,"formulaVe'
    'rsion":null,"calendarReference":null}},{"axis":"NOTIFICATION_DELIVERY","state":"UNKNO'
    'WN","reason":"DELIVERY_UNVERIFIED","observation":null}],"rules":[{"facts":{"ownerKind'
    '":"ORDINARY_RULE","ownerId":"low-buy","side":"BUY","requirements":{"inventory":true,"'
    'sellability":false,"quote":false,"simulationBook":false,"costBasis":false,"fees":fals'
    'e,"economics":false},"expectedTarget":{"kind":"INTRADAY","bucket_end":"2026-09-14T10:'
    '05:00+08:00"},"evaluatedTarget":{"kind":"INTRADAY","bucket_end":"2026-09-14T10:05:00+'
    '08:00"},"evaluatedAt":"2026-09-14T10:05:15+08:00","observation":{"context":{"planVers'
    'ionId":"c77a7169-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0b7be911e72d2a3a826e58c'
    '8ee04e77da25ea5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d'
    '7e1a1e48d96fe1133518e21c0cda12b373d","coverageHash":"2a4aecea2009d6f9a68a08070a85c41e'
    '53f9d4dfd4dca464173fac44d026f0ce","reviewReceiptHash":"f3386f13ca1f54275825c003233736'
    '63200e211564c5df9938beb591e3a7390b","activationRevision":1,"runtimeGeneration":"04bd1'
    'e22-ff58-4743-a479-b80beaa653c1","inventoryRevision":1,"bookRevision":null},"availabi'
    'lity":"CURRENT","observedAt":"2026-09-14T10:05:15+08:00","asOf":"2026-09-14T10:05:15+'
    '08:00","expiresAt":"2026-09-14T10:05:45+08:00","evidenceRefs":["a73b1797bb1a1d4ef21a3'
    '7c2d510305432ac52805f7bc383b571d272f96e7811"],"provider":null,"priceBasis":null,"form'
    'ulaVersion":null,"calendarReference":null},"rootOutcome":"SATISFIED","leaves":[{"cond'
    'itionPath":"condition.conditions[0]","state":"CONDITION_TRUE","reason":null,"evidence'
    'Refs":["a73b1797bb1a1d4ef21a37c2d510305432ac52805f7bc383b571d272f96e7811"]},{"conditi'
    'onPath":"condition.conditions[1]","state":"CONDITION_TRUE","reason":null,"evidenceRef'
    's":["a73b1797bb1a1d4ef21a37c2d510305432ac52805f7bc383b571d272f96e7811"]}],"expectedCo'
    'nfirmation":null,"execution":{"approvedQuantity":100,"consumed":false,"executionWindo'
    'w":"CURRENT_SESSION","windowState":"OPEN","eligible":true,"reason":null}},"state":"CO'
    'NDITION_TRUE","reason":null},{"facts":{"ownerKind":"ORDINARY_RULE","ownerId":"sell-10'
    '0","side":"SELL","requirements":{"inventory":true,"sellability":true,"quote":false,"s'
    'imulationBook":false,"costBasis":false,"fees":false,"economics":false},"expectedTarge'
    't":{"kind":"INTRADAY","bucket_end":"2026-09-14T10:05:00+08:00"},"evaluatedTarget":{"k'
    'ind":"INTRADAY","bucket_end":"2026-09-14T10:05:00+08:00"},"evaluatedAt":"2026-09-14T1'
    '0:05:15+08:00","observation":{"context":{"planVersionId":"c77a7169-91d3-40b6-8e73-767'
    '6860c2d6e","contentHash":"c0b7be911e72d2a3a826e58c8ee04e77da25ea5a66e59fc133f7d4c5ffc'
    'b0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1d7e1a1e48d96fe1133518e21c0cda12b373d'
    '","coverageHash":"2a4aecea2009d6f9a68a08070a85c41e53f9d4dfd4dca464173fac44d026f0ce","'
    'reviewReceiptHash":"f3386f13ca1f54275825c00323373663200e211564c5df9938beb591e3a7390b"'
    ',"activationRevision":1,"runtimeGeneration":"04bd1e22-ff58-4743-a479-b80beaa653c1","i'
    'nventoryRevision":1,"bookRevision":null},"availability":"CURRENT","observedAt":"2026-'
    '09-14T10:05:15+08:00","asOf":"2026-09-14T10:05:15+08:00","expiresAt":"2026-09-14T10:0'
    '5:45+08:00","evidenceRefs":["a73b1797bb1a1d4ef21a37c2d510305432ac52805f7bc383b571d272'
    'f96e7811"],"provider":null,"priceBasis":null,"formulaVersion":null,"calendarReference'
    '":null},"rootOutcome":"UNSATISFIED","leaves":[{"conditionPath":"condition","state":"C'
    'ONDITION_FALSE","reason":null,"evidenceRefs":["a73b1797bb1a1d4ef21a37c2d510305432ac52'
    '805f7bc383b571d272f96e7811"]}],"expectedConfirmation":null,"execution":{"approvedQuan'
    'tity":null,"consumed":null,"executionWindow":null,"windowState":"UNKNOWN","eligible":'
    'null,"reason":null}},"state":"CONDITION_FALSE","reason":null},{"facts":{"ownerKind":"'
    'ALERT_RULE","ownerId":"risk-below-950","side":null,"requirements":{"inventory":false,'
    '"sellability":false,"quote":false,"simulationBook":false,"costBasis":false,"fees":fal'
    'se,"economics":false},"expectedTarget":{"kind":"INTRADAY","bucket_end":"2026-09-14T10'
    ':05:00+08:00"},"evaluatedTarget":{"kind":"INTRADAY","bucket_end":"2026-09-14T10:05:00'
    '+08:00"},"evaluatedAt":"2026-09-14T10:05:15+08:00","observation":{"context":{"planVer'
    'sionId":"c77a7169-91d3-40b6-8e73-7676860c2d6e","contentHash":"c0b7be911e72d2a3a826e58'
    'c8ee04e77da25ea5a66e59fc133f7d4c5ffcb0b71","sourceHash":"cc0766cf9e8f4c8ca3f5a69436f1'
    'd7e1a1e48d96fe1133518e21c0cda12b373d","coverageHash":"2a4aecea2009d6f9a68a08070a85c41'
    'e53f9d4dfd4dca464173fac44d026f0ce","reviewReceiptHash":"f3386f13ca1f54275825c00323373'
    '663200e211564c5df9938beb591e3a7390b","activationRevision":1,"runtimeGeneration":"04bd'
    '1e22-ff58-4743-a479-b80beaa653c1","inventoryRevision":1,"bookRevision":null},"availab'
    'ility":"CURRENT","observedAt":"2026-09-14T10:05:15+08:00","asOf":"2026-09-14T10:05:15'
    '+08:00","expiresAt":"2026-09-14T10:05:45+08:00","evidenceRefs":["a73b1797bb1a1d4ef21a'
    '37c2d510305432ac52805f7bc383b571d272f96e7811"],"provider":null,"priceBasis":null,"for'
    'mulaVersion":null,"calendarReference":null},"rootOutcome":"UNSATISFIED","leaves":[{"c'
    'onditionPath":"condition","state":"CONDITION_FALSE","reason":null,"evidenceRefs":["a7'
    '3b1797bb1a1d4ef21a37c2d510305432ac52805f7bc383b571d272f96e7811"]}],"expectedConfirmat'
    'ion":null,"execution":{"approvedQuantity":null,"consumed":null,"executionWindow":null'
    ',"windowState":"UNKNOWN","eligible":null,"reason":null}},"state":"CONDITION_FALSE","r'
    'eason":null}],"summary":"UNKNOWN","freshUntil":null}'
)
A6_SHA256 = "0582e8054b3a82437671d705298592881f2ea1aaf27951715d15236529be4463"
A6_BYTES = 19942


def test_actual_a6_preimage_roundtrips_without_new_optional_fields():
    assert len(A6_JSON.encode()) == A6_BYTES
    assert hashlib.sha256(A6_JSON.encode()).hexdigest() == A6_SHA256
    restored = models.ReadinessAssessment.model_validate_json(A6_JSON)
    assert restored.model_dump_json(by_alias=True) == A6_JSON


EVENT = UUID("6b420d6c-d777-4193-ac39-6920241305ea")


def attempt(**changes):
    values = dict(
        id="attempt-actual-1",
        event_id=EVENT,
        channel=DeliveryChannel.IN_APP,
        attempt=1,
        status=DeliveryAttemptStatus.DELIVERED,
        response_code=None,
        next_retry_at=None,
        delivered_at=NOW - timedelta(seconds=1),
        error_code=None,
    )
    values.update(changes)
    return models.ReadinessDeliveryAttempt(**values)


def channel(**changes):
    values = dict(
        channel=DeliveryChannel.IN_APP,
        configured=True,
        enabled=True,
        eligible=None,
        latest_attempt=attempt(),
    )
    values.update(changes)
    return models.ReadinessNotificationChannel(**values)


def notice(**changes):
    values = dict(
        event_id=EVENT,
        cause_id="original-signal-1",
        created_at=NOW - timedelta(seconds=2),
        observation=observation(),
        channels=(channel(),),
    )
    values.update(changes)
    return models.ReadinessNotificationFacts(**values)


def test_new_nullable_facts_are_omitted_without_changing_old_execution_shape():
    value = rule()
    output = value.model_dump(mode="json", by_alias=True)
    assert "money" not in output and "notification" not in output
    assert output["execution"] == dict(
        approvedQuantity=None,
        consumed=None,
        executionWindow=None,
        windowState="UNKNOWN",
        eligible=None,
        reason=None,
    )
    for name in ("signalId", "signalRevision", "executionDate", "observation", "blockers"):
        assert name not in output["execution"]


def test_money_reuses_native_fail_results_without_calculating_or_granting(monkeypatch):
    from tests.unit.test_p2_economics import calc
    from tests.unit.test_p3_policy_contract import p3_payload

    from trade_plan_monitor.decision import p2_economics, p3_capital
    from trade_plan_monitor.domain.p3_policy_models import P3TradePlan

    raw = p3_payload()
    raw["position"]["limit"]["capital_policy"]["cap_fen"] = 1
    plan = P3TradePlan.model_validate(raw)
    capital = p3_capital.assess_capital(
        plan.position,
        quantity=100,
        price_fen=1000,
        total_qty=0,
        retained_basis_fen=None,
        symbol=plan.symbol,
        session=date(2026, 10, 26),
    )
    economics = calc(entry_fen=1001)
    assert capital.outcome == economics.outcome == "FAIL"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("DTO must not calculate native results")

    monkeypatch.setattr(p3_capital, "assess_capital", forbidden)
    monkeypatch.setattr(p2_economics, "calculate_economics", forbidden)
    value = models.ReadinessMoneyFacts(
        inputs=models.AxisReadiness(
            axis="INVENTORY_CAPITAL", state="PASS", observation=observation()
        ),
        capital=capital,
        economics=economics,
    )
    assert value.capital is capital and value.economics is economics
    assert (
        value.inputs.state == "PASS" and value.capital.outcome == value.economics.outcome == "FAIL"
    )
    combined = rule(money=value, execution=models.ReadinessExecutionState(approved_quantity=300))
    assert combined.money.capital.quantity == 100
    assert combined.execution.approved_quantity == 300
    assert value.model_dump(mode="json")["capital"] == capital.model_dump(mode="json")
    assert value.model_dump(mode="json")["economics"] == economics.model_dump(mode="json")
    assert (
        models.ReadinessMoneyFacts.model_validate_json(value.model_dump_json(by_alias=True))
        == value
    )
    invalid = json.loads(value.model_dump_json())
    invalid["capital"]["price_fen"] += 1
    with pytest.raises(ValidationError):
        models.ReadinessMoneyFacts.model_validate_json(json.dumps(invalid))


def test_money_unknown_results_are_absent_and_wrong_axis_is_rejected():
    value = models.ReadinessMoneyFacts(
        inputs=models.AxisReadiness(
            axis="INVENTORY_CAPITAL", state="UNKNOWN", reason="DEPENDENCY_UNVERIFIED"
        )
    )
    assert value.capital is None and value.economics is None
    assert set(value.model_dump()) == {"inputs"}
    with pytest.raises(ValidationError):
        value.model_copy(
            update={
                "inputs": models.AxisReadiness(
                    axis="DATA_EVALUATION", state="PASS", observation=observation()
                )
            }
        )


def test_explicit_null_additions_are_omitted_and_native_results_remain_strict():
    value = rule(
        money=None,
        notification=None,
        execution=models.ReadinessExecutionState(
            signal_id=None,
            signal_revision=None,
            execution_date=None,
            observation=None,
            blockers=None,
        ),
    )
    assert "money" not in value.model_dump() and "notification" not in value.model_dump()
    axis = models.AxisReadiness(
        axis="INVENTORY_CAPITAL", state="UNKNOWN", reason="DEPENDENCY_UNVERIFIED"
    )
    with pytest.raises(ValidationError):
        models.ReadinessMoneyFacts(inputs=axis, economics={"outcome": "UNKNOWN", "quantity": True})
    with pytest.raises(ValidationError):
        models.ReadinessMoneyFacts(inputs=axis, economics={"outcome": "UNKNOWN", "quantity": "100"})
    with pytest.raises(ValidationError):
        models.ReadinessMoneyFacts(inputs=axis, economics={"outcome": "UNKNOWN", "blockers": []})
    for invalid in (True, "100"):
        with pytest.raises(ValidationError):
            models.ReadinessMoneyFacts.model_validate_json(
                json.dumps(
                    dict(
                        inputs=axis.model_dump(mode="json"),
                        economics=dict(outcome="UNKNOWN", quantity=invalid, blockers=[]),
                    )
                )
            )


@pytest.mark.parametrize(
    "consumed,eligible", [(None, None), (False, None), (True, False), (False, True)]
)
def test_execution_preserves_three_values_without_deriving_eligibility(consumed, eligible):
    value = models.ReadinessExecutionState(
        signal_id="exact-signal",
        signal_revision=1,
        execution_date=None,
        consumed=consumed,
        eligible=eligible,
        observation=observation(),
        blockers=(),
    )
    assert value.consumed is consumed and value.eligible is eligible
    assert value.execution_date is None and "executionDate" not in value.model_dump(by_alias=True)
    assert value.blockers == () and value.model_dump(mode="json")["blockers"] == []
    assert value.observation == observation()


@pytest.mark.parametrize(
    "values",
    [
        dict(signal_id="one"),
        dict(signal_revision=1),
        dict(signal_id="one", signal_revision=True),
        dict(signal_id="one", signal_revision=-1),
        dict(consumed=0),
        dict(eligible=1),
        dict(blockers=["CAPITAL_LIMIT_EXCEEDED"]),
    ],
)
def test_execution_requires_paired_strict_signal_references(values):
    with pytest.raises(ValidationError):
        models.ReadinessExecutionState(**values)


def test_execution_complete_blockers_and_legacy_approved_fact_remain_independent():
    value = models.ReadinessExecutionState(
        approved_quantity=100,
        eligible=None,
        blockers=("CAPITAL_LIMIT_EXCEEDED", "HIGHER_PRIORITY_RISK"),
    )
    assert value.blockers == ("CAPITAL_LIMIT_EXCEEDED", "HIGHER_PRIORITY_RISK")
    assert value.eligible is None and value.signal_id is None
    assert models.ReadinessExecutionState().blockers is None


def test_native_secret_free_attempt_projects_exactly():
    native = DeliveryAttemptRecord(
        id="native-attempt",
        event_id=EVENT,
        channel=DeliveryChannel.CONSOLE,
        attempt=2,
        status=DeliveryAttemptStatus.RETRY_PENDING,
        response_code=None,
        next_retry_at=NOW + timedelta(seconds=30),
        delivered_at=None,
        error_code=ChannelErrorCode.CONSOLE_WRITE_FAILED,
    )
    value = models.ReadinessDeliveryAttempt.model_validate(native, from_attributes=True)
    assert value.model_dump() == asdict(native)
    assert value.status is native.status and value.error_code is native.error_code


def test_current_eligibility_does_not_rewrite_historical_classification_or_attempt():
    value = channel(
        eligible=False,
        historical_status=RecoveryDeliveryStatus.ELIGIBLE,
        historical_updated_at=NOW - timedelta(minutes=1),
    )
    observed = notice(created_at=NOW - timedelta(minutes=2), channels=(value,))
    assert observed.channels[0].eligible is False
    assert observed.channels[0].historical_status is RecoveryDeliveryStatus.ELIGIBLE
    assert observed.channels[0].latest_attempt.status is DeliveryAttemptStatus.DELIVERED
    assert observed.channels[0].historical_updated_at == NOW - timedelta(minutes=1)


def test_absent_event_and_attempt_do_not_manufacture_pending_or_failed():
    value = models.ReadinessNotificationFacts(
        channels=(channel(configured=None, enabled=False, latest_attempt=None),)
    )
    assert value.event_id is None and value.channels[0].eligible is None
    assert value.channels[0].historical_status is None and value.channels[0].latest_attempt is None
    assert "latestAttempt" not in value.channels[0].model_dump(by_alias=True)
    assert value.channels[0].enabled is False and value.channels[0].configured is None


def test_in_app_receipt_cannot_fill_unverified_webhook_facts():
    webhook = channel(
        channel=DeliveryChannel.WEBHOOK, configured=None, enabled=None, latest_attempt=None
    )
    value = notice(channels=(channel(), webhook))
    assert value.channels[0].latest_attempt.status is DeliveryAttemptStatus.DELIVERED
    assert value.channels[1].configured is None and value.channels[1].eligible is None
    assert value.channels[1].latest_attempt is None


def test_fact_json_roundtrip_keeps_original_enums_aliases_and_execution_date():
    value = notice()
    encoded = value.model_dump_json(by_alias=True)
    restored = models.ReadinessNotificationFacts.model_validate_json(encoded)
    assert restored == value and restored.channels[0].channel is DeliveryChannel.IN_APP
    assert restored.channels[0].latest_attempt.status is DeliveryAttemptStatus.DELIVERED
    assert json.loads(encoded)["eventId"] == str(EVENT)
    execution = models.ReadinessExecutionState(
        signal_id="signal-original", signal_revision=3, execution_date=NOW.date()
    )
    assert (
        models.ReadinessExecutionState.model_validate_json(execution.model_dump_json(by_alias=True))
        == execution
    )


@pytest.mark.parametrize("field", ["configured", "enabled", "eligible"])
def test_unverified_channel_flags_are_strict_three_values(field):
    for value in (None, False, True):
        assert getattr(channel(**{field: value}), field) is value
    with pytest.raises(ValidationError):
        channel(**{field: 0})


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "over_limit",
        "wrong_event",
        "wrong_channel",
        "event_absent",
        "orphan_target",
        "historical_without_time",
        "historical_time_without_status",
    ],
)
def test_notification_rejects_incoherent_record_bindings(change):
    from trade_plan_monitor.decision.models import OfficialCloseEvaluationTarget

    with pytest.raises(ValidationError):
        if change == "duplicate":
            notice(channels=(channel(), channel()))
        elif change == "over_limit":
            notice(channels=(channel(),) * 4)
        elif change == "wrong_event":
            notice(channels=(channel(latest_attempt=attempt(event_id=UUID(int=1))),))
        elif change == "wrong_channel":
            channel(latest_attempt=attempt(channel=DeliveryChannel.WEBHOOK))
        elif change == "event_absent":
            notice(event_id=None, cause_id=None, created_at=None)
        elif change == "orphan_target":
            models.ReadinessNotificationFacts(
                target=OfficialCloseEvaluationTarget(trade_date=NOW.date())
            )
        elif change == "historical_without_time":
            channel(historical_status=RecoveryDeliveryStatus.HOLD)
        else:
            channel(historical_updated_at=NOW)


@pytest.mark.parametrize(
    "status,delivered_at",
    [
        (DeliveryAttemptStatus.DELIVERED, None),
        (DeliveryAttemptStatus.CLAIMED, NOW),
        (DeliveryAttemptStatus.RETRY_PENDING, NOW),
        (DeliveryAttemptStatus.FAILED, NOW),
    ],
)
def test_only_actual_delivered_shape_carries_delivery_time(status, delivered_at):
    with pytest.raises(ValidationError):
        attempt(status=status, delivered_at=delivered_at)


@pytest.mark.parametrize("change", ["before_event", "future_delivery", "future_created", "naive"])
def test_notification_times_are_original_ordered_and_timezone_aware(change):
    with pytest.raises(ValidationError):
        if change == "before_event":
            notice(
                channels=(channel(latest_attempt=attempt(delivered_at=NOW - timedelta(days=1))),)
            )
        elif change == "future_delivery":
            notice(
                channels=(channel(latest_attempt=attempt(delivered_at=NOW + timedelta(seconds=1))),)
            )
        elif change == "future_created":
            notice(created_at=NOW + timedelta(seconds=1), channels=())
        else:
            attempt(delivered_at=NOW.replace(tzinfo=None))


def test_event_target_and_historical_time_cannot_be_future_observations():
    from trade_plan_monitor.decision.models import IntradayEvaluationTarget

    with pytest.raises(ValidationError):
        notice(target=IntradayEvaluationTarget(bucket_end=NOW + timedelta(minutes=5)))
    with pytest.raises(ValidationError):
        notice(
            channels=(
                channel(
                    historical_status=RecoveryDeliveryStatus.HOLD,
                    historical_updated_at=NOW + timedelta(seconds=1),
                ),
            )
        )
    with pytest.raises(ValidationError):
        notice(
            channels=(
                channel(
                    historical_status=RecoveryDeliveryStatus.HOLD,
                    historical_updated_at=NOW - timedelta(seconds=3),
                ),
            )
        )


def test_delivery_shape_rejects_contradictory_errors_and_hides_unsafe_input():
    with pytest.raises(ValidationError):
        attempt(error_code=ChannelErrorCode.CHANNEL_FAILURE)
    with pytest.raises(ValidationError):
        attempt(next_retry_at=NOW)
    with pytest.raises(ValidationError) as invalid:
        attempt(error_code="SYNTHETIC_SECRET_RAW_ERROR")
    assert "SYNTHETIC_SECRET_RAW_ERROR" not in str(invalid.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt", True),
        ("attempt", 0),
        ("response_code", 99),
        ("response_code", 600),
        ("response_code", True),
        ("error_code", "RAW URL TOKEN SECRET"),
        ("status", "QUEUED"),
        ("channel", "EMAIL"),
    ],
)
def test_attempt_uses_original_closed_safe_enums_and_strict_fields(field, value):
    with pytest.raises(ValidationError):
        attempt(**{field: value})


@pytest.mark.parametrize(
    "name,secret",
    [
        ("attempt", "endpoint"),
        ("attempt", "token"),
        ("attempt", "raw_error"),
        ("channel", "endpoint"),
        ("notice", "token"),
        ("money", "account_balance"),
        ("execution", "approval_token"),
    ],
)
def test_facts_forbid_secret_and_unregistered_fields(name, secret):
    factories = dict(
        attempt=attempt,
        channel=channel,
        notice=notice,
        money=lambda **fields: models.ReadinessMoneyFacts(
            inputs=models.AxisReadiness(
                axis="INVENTORY_CAPITAL", state="UNKNOWN", reason="DEPENDENCY_UNVERIFIED"
            ),
            **fields,
        ),
        execution=models.ReadinessExecutionState,
    )
    with pytest.raises(ValidationError):
        factories[name](**{secret: "SYNTHETIC_SECRET"})


@pytest.mark.parametrize("kind", ["money", "attempt", "channel", "notice", "execution"])
def test_new_facts_are_closed_frozen_and_strict(kind):
    values = dict(
        money=lambda: models.ReadinessMoneyFacts(
            inputs=models.AxisReadiness(
                axis="INVENTORY_CAPITAL", state="UNKNOWN", reason="DEPENDENCY_UNVERIFIED"
            )
        ),
        attempt=attempt,
        channel=channel,
        notice=notice,
        execution=models.ReadinessExecutionState,
    )
    value = values[kind]()
    assert value.model_config["extra"] == "forbid"
    assert value.model_config["frozen"] is True and value.model_config["strict"] is True
    with pytest.raises(ValidationError):
        value.unregistered_field = True


def test_new_unknown_facts_do_not_change_axes_authority_or_null_freshness():
    from trade_plan_monitor.web.plan_readiness_summary import summarize_readiness

    unknown = models.AxisReadiness(
        axis="NOTIFICATION_DELIVERY", state="UNKNOWN", reason="DELIVERY_UNVERIFIED"
    )
    value = rule(money=None, notification=models.ReadinessNotificationFacts())
    assessed = summarize_readiness(
        snapshot(rules=(value,), replacements={"NOTIFICATION_DELIVERY": unknown})
    )
    assert assessed.authority_granted is False and assessed.summary == "UNKNOWN"
    assert assessed.fresh_until is None
    for illegal in (True, 0, None):
        with pytest.raises(ValidationError):
            assessed.model_copy(update={"authority_granted": illegal})


def test_original_owner_and_leaf_limits_are_not_relaxed():
    value = snapshot()
    with pytest.raises(ValidationError):
        value.model_copy(update={"rules": (rule(),) * 77})
    leaves = tuple(
        rule().leaves[0].model_copy(update={"condition_path": f"condition[{i}]"}) for i in range(51)
    )
    with pytest.raises(ValidationError):
        rule(leaves=leaves)
    assert models.ReadinessExecutionState().model_dump_json() == (
        '{"approved_quantity":null,"consumed":null,"execution_window":null,'
        '"window_state":"UNKNOWN","eligible":null,"reason":null}'
    )


def test_exact_existing_owner_and_leaf_limits_still_accept_complete_shape():
    leaves = tuple(
        rule().leaves[0].model_copy(update={"condition_path": f"condition[{i}]"}) for i in range(50)
    )
    owners = tuple(rule(owner_id=f"owner-{i}", leaves=leaves if i == 0 else ()) for i in range(76))
    value = snapshot(rules=owners)
    assert len(value.rules) == 76 and sum(len(item.leaves) for item in value.rules) == 50
