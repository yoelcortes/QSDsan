#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
QSDsan: Quantitative Sustainable Design for sanitation and resource recovery systems

This module is developed by:
    Yalin Li <zoe.yalin.li@gmail.com>

This module is under the University of Illinois/NCSA Open Source License.
Please refer to https://github.com/QSD-Group/QSDsan/blob/main/LICENSE.txt
for license details.
'''

import math
import flexsolve as flx
import biosteam as bst
from .. import SanUnit

__all__ = ('SludgeHandling', 'BeltThickener', 'SludgeCentrifuge')


class SludgeHandling(SanUnit):
    '''
    A generic class for handling of wastewater treatmnet sludge.

    The 0th outs is the water-rich supernatant (effluent) and
    the 1st outs is the solid-rich sludge.

    Two pumps (one for the supernatant and one for sludge) are included.

    Separation split is determined by the moisture (i.e., water) content
    of the sludge, soluble chemicals will have the same split as water,
    insolubles chemicals will all go to the retentate.

    Parameters
    ----------
    sludge_moisture : float
        Moisture content of the sludge, [wt% water].
    solids : Iterable(str)
        IDs of the solid components.
        If not provided, will be set to the default `solids` attribute of the components.

    References
    ----------
    .. [1] Shoener et al., Design of Anaerobic Membrane Bioreactors for the
    Valorization of Dilute Organic Carbon Waste Streams.
    Energy Environ. Sci. 2016, 9 (3), 1102–1112.
    https://doi.org/10.1039/C5EE03715H.
    '''

    _graphics = bst.Splitter._graphics
    _ins_size_is_fixed = False
    _N_outs = 2
    auxiliary_unit_names = ('effluent_pump', 'sludge_pump')


    def __init__(self, ID='', ins=None, outs=(), thermo=None,
                 init_with='WasteStream', isdynamic=False,
                 sludge_moisture=0.96, solids=()):
        SanUnit.__init__(self, ID, ins, outs, thermo,
                         init_with=init_with, isdynamic=isdynamic)
        self.sludge_moisture = sludge_moisture
        cmps = self.components
        self.solids = solids or cmps.solids
        self.solubles = tuple([i.ID for i in cmps if i.ID not in self.solids])
        self.effluent_pump = bst.Pump(f'{self.ID}_eff')
        self.sludge_pump = bst.Pump(f'{self.ID}_sludge')
        self._mixed = self.ins[0].copy()


    @staticmethod
    def _mc_at_split(split, solubles, mixed, eff, sludge, target_mc):
        eff.imass[solubles] = mixed.imass[solubles] * split
        sludge.imass[solubles] = mixed.imass[solubles] - eff.imass[solubles]
        mc = sludge.imass['Water'] / sludge.F_mass
        return mc-target_mc


    def _run(self):
        eff, sludge = self.outs
        solubles, solids = self.solubles, self.solids

        mixed = self._mixed
        mixed.mix_from(self.ins)
        eff.T = sludge.T = mixed.T

        sludge.copy_flow(mixed, solids, remove=True) # all solids go to sludge
        eff.copy_flow(mixed, solubles)

        flx.IQ_interpolation(
                f=self._mc_at_split, x0=1e-3, x1=1.-1e-3,
                args=(solubles, mixed, eff, sludge, self.sludge_moisture),
                checkbounds=False)


    def _cost(self):
        pumps = (self.effluent_pump, self.sludge_pump)
        for i in range(2):
            pumps[i].ins[0] = self.outs[i].copy() # use `.proxy()` will interfere `_run`
            pumps[i].simulate()
            self.power_utility.rate += pumps[i].power_utility.rate


class BeltThickener(SludgeHandling):
    '''
    Gravity belt thickener (GBT) designed based on the manufacture specification
    data sheet. [1]_

    The 0th outs is the water-rich supernatant (effluent) and
    the 1st outs is the solid-rich sludge.

    Key parameters include:
        - Capacity: 80-100 m3/h.
        - Influent solids concentration: 0.2-1%.
        - Sludge cake moisture content: 90-96%.
        - Motor power: 3 (driving motor) and 1.1 agitator motor.
        - Belt width: 2.5 m.
        - Weight: 2350 kg.
        - Quote price: $3680 ea for three or more sets.

    The bare module (installation) factor is from Table 25 in Humbird et al. [2]_
    (solids handling equipment).

    Parameters
    ----------
    sludge_moisture : float
        Moisture content of the thickened sludge, [wt% water].
    solubles : tuple
        IDs of the soluble chemicals.
        Note that all chemicals that are not included in this tuple and not
        locked as gas phase (i.e., `chemical.locked_state!='g'`) will be
        treated as solids in simulation.
    max_capacity : float
        Maximum hydraulic loading per belt thickener, [m3/h].
    power_demand : float
        Total power demand of each belt thickener, [kW].

    References
    ----------
    .. [1] `Industrial filtering equipment gravity thickener rotary thickening belt filter press \
    <https://www.alibaba.com/product-detail/Industrial-filtering-equipment-gravity-thickener-rotary_60757627922.html?spm=a2700.galleryofferlist.normal_offer.d_title.78556be9t8szku>`_
    Data obtained on 7/21/2021.

    .. [2] Humbird et al., Process Design and Economics for Biochemical Conversion of
    Lignocellulosic Biomass to Ethanol: Dilute-Acid Pretreatment and Enzymatic
    Hydrolysis of Corn Stover; Technical Report NREL/TP-5100-47764;
    National Renewable Energy Lab (NREL), 2011.
    https://www.nrel.gov/docs/fy11osti/47764.pdf
    '''

    def __init__(self, ID='', ins=None, outs=(), thermo=None,
                 sludge_moisture=0.96, solubles=(),
                 max_capacity=100, power_demand=4.1):
        SludgeHandling.__init__(self, ID, ins, outs, thermo,
                                sludge_moisture=sludge_moisture,
                                solubles=solubles)
        self.max_capacity = max_capacity
        self.power_demand = power_demand


    def _design(self):
        self._N_thickener = N = math.ceil(self._mixed.F_vol/self.max_capacity)
        self.design_results['Number of thickners'] = N
        self.F_BM['Thickeners'] = 1.7 # ref [2]
        self.baseline_purchase_costs['Thickeners'] = 4000 * N
        self.power_utility.rate = self.power_demand * N


    @property
    def N_thickener(self):
        '''[int] Number of required belt thickeners.'''
        return self._N


class SludgeCentrifuge(SludgeHandling, bst.SolidsCentrifuge):
    '''
    Solid centrifuge for sludge dewatering.

    `_run` and `_cost` are based on `SludgeHandling` and `_design`
    is based on `SolidsCentrifuge`.

    The 0th outs is the water-rich supernatant (effluent) and
    the 1st outs is the solid-rich sludge.

    Parameters
    ----------
    sludge_moisture : float
        Moisture content of the thickened sludge, [wt% water].
    solubles : tuple
        IDs of the soluble chemicals.
        Note that all chemicals that are not included in this tuple and not
        locked as gas phase (i.e., `chemical.locked_state!='g'`) will be
        treated as solids in simulation.
    '''

    def __init__(self, ID='', ins=None, outs=(), thermo=None,
                 sludge_moisture=0.8, solubles=(),
                 centrifuge_type='scroll_solid_bowl'):
        SludgeHandling.__init__(self, ID, ins, outs, thermo,
                                sludge_moisture=sludge_moisture,
                                solubles=solubles)
        self.centrifuge_type = centrifuge_type

    _run = SludgeHandling._run

    _design = bst.SolidsCentrifuge._design

    _cost = SludgeHandling._cost