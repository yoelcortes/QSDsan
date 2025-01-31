#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
QSDsan: Quantitative Sustainable Design for sanitation and resource recovery systems

This module is developed by:
    Yalin Li <mailto.yalin.li@gmail.com>
    Joy Zhang <joycheung1994@gmail.com>

This module is under the University of Illinois/NCSA Open Source License.
Please refer to https://github.com/QSD-Group/QSDsan/blob/main/LICENSE.txt
for license details.
'''


from math import ceil, pi
import numpy as np
from . import Decay
from .. import SanUnit, Construction, WasteStream
from ..sanunits import HXutility, WWTpump, CSTR
from ..utils import ospath, load_data, data_path, auom, calculate_excavation_volume
__all__ = (
    'AnaerobicBaffledReactor',
    'AnaerobicCSTR',
    'AnaerobicDigestion',
    'SludgeDigester',
    )


# %%

abr_path = ospath.join(data_path, 'sanunit_data/_anaerobic_baffled_reactor.tsv')

class AnaerobicBaffledReactor(SanUnit, Decay):
    '''
    Anaerobic baffled reactor with the production of biogas based on
    `Trimmer et al. <https://doi.org/10.1021/acs.est.0c03296>`_

    To enable life cycle assessment, the following impact items should be pre-constructed:
    `Concrete`, `Gravel`, `Excavation`.

    Parameters
    ----------
    ins : Iterable
        Waste for treatment.
    outs : Iterable
        Treated waste, biogas, fugitive CH4, and fugitive N2O.
    degraded_components : tuple
        IDs of components that will degrade (at the same removal as `COD_removal`).
    if_capture_biogas : bool
        If produced biogas will be captured, otherwise it will be treated
        as fugitive CH4.
    if_N2O_emission : bool
        If considering fugitive N2O generated from the degraded N.

    Examples
    --------
    `bwaise systems <https://github.com/QSD-Group/EXPOsan/blob/main/exposan/bwaise/systems.py>`_

    References
    ----------
    [1] Trimmer et al., Navigating Multidimensional Social–Ecological System
    Trade-Offs across Sanitation Alternatives in an Urban Informal Settlement.
    Environ. Sci. Technol. 2020, 54 (19), 12641–12653.
    https://doi.org/10.1021/acs.est.0c03296.

    See Also
    --------
    :ref:`qsdsan.sanunits.Decay <sanunits_Decay>`
    '''

    gravel_density = 1600

    def __init__(self, ID='', ins=None, outs=(), thermo=None, init_with='WasteStream',
                 degraded_components=('OtherSS',), if_capture_biogas=True,
                 if_N2O_emission=False, **kwargs):

        SanUnit.__init__(self, ID, ins, outs, thermo, init_with, F_BM_default=1)
        self.degraded_components = tuple(degraded_components)
        self.if_capture_biogas = if_capture_biogas
        self.if_N2O_emission = if_N2O_emission

        self.construction = (
            Construction('concrete', linked_unit=self, item='Concrete', quantity_unit='m3'),
            Construction('gravel', linked_unit=self, item='Gravel', quantity_unit='kg'),
            Construction('excavation', linked_unit=self, item='Excavation', quantity_unit='m3'),
            )

        data = load_data(path=abr_path)
        for para in data.index:
            value = float(data.loc[para]['expected'])
            setattr(self, '_'+para, value)
        del data

        for attr, value in kwargs.items():
            setattr(self, attr, value)

    _N_ins = 1
    _N_outs = 4

    def _run(self):
        waste = self.ins[0]
        treated, biogas, CH4, N2O = self.outs
        treated.copy_like(self.ins[0])
        biogas.phase = CH4.phase = N2O.phase = 'g'

        # COD removal
        _COD = waste._COD or waste.COD
        COD_deg = _COD*waste.F_vol/1e3*self.COD_removal # kg/hr
        treated._COD *= (1-self.COD_removal)
        treated.imass[self.degraded_components] *= (1-self.COD_removal)

        CH4_prcd = COD_deg*self.MCF_decay*self.max_CH4_emission
        if self.if_capture_biogas:
            biogas.imass['CH4'] = CH4_prcd
            CH4.empty()
        else:
            CH4.imass['CH4'] = CH4_prcd
            biogas.empty()

        N_tot = waste.TN/1e3 * waste.F_vol
        N_loss_tot = N_tot * self.N_removal
        NH3_rmd, NonNH3_rmd = \
            self.allocate_N_removal(N_loss_tot, waste.imass['NH3'])
        treated.imass ['NH3'] = waste.imass['NH3'] - NH3_rmd
        treated.imass['NonNH3'] = waste.imass['NonNH3'] - NonNH3_rmd

        if self.if_N2O_emission:
            N2O.imass['N2O'] = N_loss_tot*self.N_max_decay*self.N2O_EF_decay*44/28
        else:
            N2O.empty()

    _units = {
        'Residence time': 'd',
        'Reactor length': 'm',
        'Reactor width': 'm',
        'Reactor height': 'm',
        'Single reactor volume': 'm3'
        }

    def _design(self):
        design = self.design_results
        design['Residence time'] = self.tau
        design['Reactor number'] = N = self.N_reactor
        design['Baffle number'] = N_b = self.N_baffle
        design['Reactor length'] = L = self.reactor_L
        design['Reactor width'] = W = self.reactor_W
        design['Reactor height'] = H = self.reactor_H
        design['Single reactor volume'] = V = L*W*H

        constr = self.construction
        concrete = N*self.concrete_thickness*(2*L*W+2*L*H+(2+N_b)*W*H)*self.add_concrete
        constr[0].quantity = concrete
        constr[1].quantity = N*V/(N_b+1) * self.gravel_density
        constr[2].quantity = N * V # excavation

        self.add_construction()


    @property
    def tau(self):
        '''[float] Residence time, [d].'''
        return self._tau
    @tau.setter
    def tau(self, i):
        self._tau = i

    @property
    def COD_removal(self):
        '''[float] Fraction of COD removed during treatment.'''
        return self._COD_removal
    @COD_removal.setter
    def COD_removal(self, i):
        self._COD_removal = i

    @property
    def N_removal(self):
        '''[float] Fraction of N removed during treatment.'''
        return self._N_removal
    @N_removal.setter
    def N_removal(self, i):
        self._N_removal = i

    @property
    def N_reactor(self):
        '''[int] Number of reactors, float will be converted to the smallest integer.'''
        return self._N_reactor
    @N_reactor.setter
    def N_reactor(self, i):
        self._N_reactor = ceil(i)

    @property
    def reactor_L(self):
        '''[float] Reactor length, [m].'''
        return self._reactor_L
    @reactor_L.setter
    def reactor_L(self, i):
        self._reactor_L = i

    @property
    def reactor_W(self):
        '''[float] Reactor width, [m].'''
        return self._reactor_W
    @reactor_W.setter
    def reactor_W(self, i):
        self._reactor_W = i

    @property
    def reactor_H(self):
        '''[float] Reactor height, [m].'''
        return self._reactor_H
    @reactor_H.setter
    def reactor_H(self, i):
        self._reactor_H = i

    @property
    def N_baffle(self):
        '''[int] Number of reactors, float will be converted to the smallest integer.'''
        return self._N_baffle
    @N_baffle.setter
    def N_baffle(self, i):
        self._N_baffle = ceil(i)

    @property
    def add_concrete(self):
        '''
        [float] Additional concrete as a fraction of the reactor concrete usage
        to account for receiving basin and biogas tank.
        '''
        return self._add_concrete
    @add_concrete.setter
    def add_concrete(self, i):
        self._add_concrete = i

    @property
    def concrete_thickness(self):
        '''[float] Thickness of the concrete wall.'''
        return self._concrete_thickness
    @concrete_thickness.setter
    def concrete_thickness(self, i):
        self._concrete_thickness = i


# %%

class AnaerobicCSTR(CSTR):
    
    '''
    An anaerpbic continuous stirred tank reactor with biogas in headspace. [1]_, [2]_

    Parameters
    ----------
    ins : :class:`WasteStream`
        Influent to the reactor.
    outs : Iterable
        Biogas and treated effluent.
    V_liq : float, optional
        Liquid-phase volume [m^3]. The default is 3400.
    V_gas : float, optional
        Headspace volume [m^3]. The default is 300.
    model : :class:`Processes`, optional
        The kinetic model, typically ADM1-like. The default is None.
    T : float, optional
        Operation temperature [K]. The default is 308.15.
    headspace_P : float, optional
        Headspace pressure, if fixed [bar]. The default is 1.013.
    external_P : float, optional
        External pressure, typically atmospheric pressure [bar]. The default is 1.013.
    pipe_resistance : float, optional
        Biogas extraction pipe resistance [m3/d/bar]. The default is 5.0e4.
    fixed_headspace_P : bool, optional
        Whether to assume fixed headspace pressure. The default is False.
    retain_cmps : Iterable[str], optional
        IDs of the components that are assumed to be retained in the reactor, ideally.
        The default is ().
    fraction_retain : float, optional
        The assumed fraction of ideal retention of select components. The default is 0.95.
    
    References
    ----------
    .. [1] Batstone, D. J.; Keller, J.; Angelidaki, I.; Kalyuzhnyi, S. V; 
        Pavlostathis, S. G.; Rozzi, A.; Sanders, W. T. M.; Siegrist, H.; 
        Vavilin, V. A. The IWA Anaerobic Digestion Model No 1 (ADM1). 
        Water Sci. Technol. 2002, 45 (10), 65–73.
    .. [2] Rosen, C.; Jeppsson, U. Aspects on ADM1 Implementation within 
        the BSM2 Framework; Lund, 2006.
    '''
    
    _N_ins = 1
    _N_outs = 2
    _ins_size_is_fixed = True
    _outs_size_is_fixed = True
    _R = 8.3145e-2 # Universal gas constant, [bar/M/K]
    
    def __init__(self, ID='', ins=None, outs=(), thermo=None,
                 init_with='WasteStream', V_liq=3400, V_gas=300, model=None,  
                 T=308.15, headspace_P=1.013, external_P=1.013, 
                 pipe_resistance=5.0e4, fixed_headspace_P=False,
                 retain_cmps=(), fraction_retain=0.95,
                 isdynamic=True, exogenous_var=(), **kwargs):
        
        super().__init__(ID=ID, ins=ins, outs=outs, thermo=thermo,
                         init_with=init_with, V_max=V_liq, aeration=None,
                         DO_ID=None, suspended_growth_model=None,
                         isdynamic=isdynamic, exogenous_var=exogenous_var, **kwargs)
        self.V_gas = V_gas
        self.T = T
        # self._S_gas = None
        self._q_gas = 0
        self._n_gas = None
        self._gas_cmp_idx = None
        self._state_keys = None
        self._S_vapor = None
        self.model = model
        self._biogas = WasteStream(phase='g')
        self.headspace_P = headspace_P
        self.external_P = external_P
        self.pipe_resistance = pipe_resistance
        self.fixed_headspace_P = fixed_headspace_P
        self._f_retain = np.array([fraction_retain if cmp.ID in retain_cmps \
                                   else 0 for cmp in self.components])
    
    def ideal_gas_law(self, p=None, S=None):
        '''Calculates partial pressure [bar] given concentration [M] at 
        operation temperature or vice versa according to the ideal gas law .'''
        # p in bar, S in M
        if p: return p/self._R/self.T
        elif S: return S*self._R*self.T

    def p_vapor(self, convert_to_bar=True):
        '''Calculates the saturated vapor pressure at operation temperature.'''
        p = self.components.H2O.Psat(self.T)
        if convert_to_bar:
            return p*auom('Pa').conversion_factor('bar')
        else: return p
        
    @property
    def DO_ID(self):
        '''Not applicable.'''
        return None
    @DO_ID.setter
    def DO_ID(self, doid):
        '''Does nothing.'''
        pass
    
    @property
    def aeration(self):
        '''Not applicable'''
        return None
    @aeration.setter
    def aeration(self, ae):
        '''Does nothing.'''
        pass
    
    V_liq = property(CSTR.V_max.fget)
    @V_liq.setter
    def V_liq(self, V):
        '''[float] The liquid-phase volume, in m^3.'''
        CSTR.V_max.fset(self, V)
    
    model = property(CSTR.suspended_growth_model.fget)
    @model.setter
    def model(self, model):
        '''[:class:`CompiledProcesses` or NoneType] Anaerobic digestion model.'''
        CSTR.suspended_growth_model.fset(self, model)
        if model is not None:
            #!!! how to make unit conversion generalizable to all models?
            self._S_vapor = self.ideal_gas_law(p=self.p_vapor())
            self._n_gas = len(model._biogas_IDs)
            self._state_keys = list(self.components.IDs) \
                + [ID+'_gas' for ID in self.model._biogas_IDs] \
                + ['Q']
            self._gas_cmp_idx = self.components.indices(self.model._biogas_IDs)
            self._state_header = self._state_keys
    
    @property
    def split(self):
        '''Not applicable.'''
        return None
    @split.setter
    def split(self, split):
        '''Does nothing.'''
        pass
    
    @property
    def headspace_P(self):
        '''Headspace total pressure [bar].'''
        return self._P_gas
    @headspace_P.setter
    def headspace_P(self, P):
        self._P_gas = P
        
    @property
    def external_P(self):
        '''External (atmospheric) pressure [bar].'''
        return self._P_atm
    @external_P.setter
    def external_P(self, P):
        self._P_atm = P
    
    @property
    def pipe_resistance(self):
        '''Gas pipe resistance coefficient [m3/d/bar].'''
        return self._k_p
    @pipe_resistance.setter
    def pipe_resistance(self, k):
        self._k_p = k

    @property
    def fixed_headspace_P(self):
        '''Headspace total pressure [bar].'''
        return self._fixed_P_gas
    @fixed_headspace_P.setter
    def fixed_headspace_P(self, b):
        self._fixed_P_gas = bool(b)
        
    @property
    def state(self):
        '''The state of the anaerobic CSTR, including component concentrations [kg/m3],
        biogas concentrations in the headspace [M biogas], and liquid flow rate [m^3/d].'''
        if self._state is None: return None
        else:
            return dict(zip(self._state_keys, self._state))

    @state.setter
    def state(self, arr):
        arr = np.asarray(arr)
        n_state = len(self._state_keys)
        if arr.shape != (n_state, ):
            raise ValueError(f'state must be a 1D array of length {n_state}')
        self._state = arr

    def _run(self):
        '''Only to converge volumetric flows.'''
        inf, = self.ins
        gas, liquid = self.outs
        liquid.copy_like(inf)
        gas.copy_like(self._biogas)
        if self._fixed_P_gas: 
            gas.P = self.headspace_P * auom('bar').conversion_factor('Pa')
        gas.T = self.T
        
    def _init_state(self):
        inf, = self._ins
        Q = inf.get_total_flow('m3/d')
        #!!! how to make unit conversion generalizable to all models?
        if self._concs is not None: Cs = self._concs * 1e-3 # mg/L to kg/m3
        else: Cs = inf.conc * 1e-3 # mg/L to kg/m3
        self._state = np.append(Cs, [0]*self._n_gas + [Q]).astype('float64')
        self._dstate = self._state * 0.

    def _update_state(self):
        arr = self._state
        gas, liquid = self._outs
        f_rtn = self._f_retain
        y = arr.copy()
        i_mass = self.components.i_mass
        chem_MW = self.components.chem_MW
        n_cmps = len(self.components)
        if liquid.state is None:
            liquid.state = np.append(y[:n_cmps]*(1-f_rtn)*1e3, y[-1])
        else:
            liquid.state[:n_cmps] = y[:n_cmps]*(1-f_rtn)*1e3  # kg/m3 to mg/L
            liquid.state[-1] = y[-1]
        if gas.state is None:
            gas.state = np.zeros(n_cmps+1)
        gas.state[self._gas_cmp_idx] = y[n_cmps:(n_cmps + self._n_gas)]
        gas.state[self.components.index('H2O')] = self._S_vapor
        gas.state[-1] = self._q_gas
        gas.state[:n_cmps] = gas.state[:n_cmps] * chem_MW / i_mass * 1e3 # i.e., M biogas to mg (measured_unit) / L

    def _update_dstate(self):
        arr = self._dstate
        gas, liquid = self._outs
        f_rtn = self._f_retain
        dy = arr.copy()
        n_cmps = len(self.components)
        if liquid.dstate is None:
            liquid.dstate = np.append(dy[:n_cmps]*(1-f_rtn)*1e3, dy[-1])
        else:
            liquid.dstate[:n_cmps] = dy[:n_cmps]*(1-f_rtn)*1e3
            liquid.dstate[-1] = dy[-1]
        if gas.dstate is None:
            # contains no info on dstate
            gas.dstate = np.zeros(n_cmps+1)

    
    def f_q_gas_fixed_P_headspace(self, rhoTs, S_gas, T):
        cmps = self.components
        gas_mass2mol_conversion = (cmps.i_mass / cmps.chem_MW)[self._gas_cmp_idx]
        self._q_gas = self._R*T/(self.P_gas-self.p_vapor(convert_to_bar=True))\
                                *self.V_liq*sum(rhoTs*gas_mass2mol_conversion)
        return self._q_gas

    def f_q_gas_var_P_headspace(self, rhoTs, S_gas, T):
        p_gas = S_gas * self._R * T
        self._P_gas = P = sum(p_gas) + self.p_vapor(convert_to_bar=True) 
        self._q_gas = self._k_p * (P - self._P_atm)
        return self._q_gas

    @property
    def ODE(self):
        if self._ODE is None:
            self._compile_ODE()
        return self._ODE
    
    def _compile_ODE(self):
        if self._model is None:
            CSTR._compile_ODE(self)
        else:
            cmps = self.components
            f_rtn = self._f_retain
            _dstate = self._dstate
            _update_dstate = self._update_dstate
            _f_rhos = self.model.rate_function
            _f_param = self.model.params_eval
            _M_stoichio = self.model.stoichio_eval
            n_cmps = len(cmps)
            n_gas = self._n_gas
            V_liq = self.V_liq
            V_gas = self.V_gas
            T = self.T
            gas_mass2mol_conversion = (cmps.i_mass / cmps.chem_MW)[self._gas_cmp_idx]
            hasexo = bool(len(self._exovars))
            f_exovars = self.eval_exo_dynamic_vars
            if self._fixed_P_gas:
                f_qgas = self.f_q_gas_fixed_P_headspace
            else:
                f_qgas = self.f_q_gas_var_P_headspace
            def dy_dt(t, QC_ins, QC, dQC_ins):
                S_liq = QC[:n_cmps]
                S_gas = QC[n_cmps: (n_cmps+n_gas)]
                Q = QC[-1]
                S_in = QC_ins[0,:-1] * 1e-3  # mg/L to kg/m3
                Q_in = QC_ins[0,-1]
                if hasexo: QC = np.append(QC, f_exovars(t))
                _f_param(QC)
                M_stoichio = _M_stoichio()
                rhos =_f_rhos(QC)
                _dstate[:n_cmps] = (Q_in*S_in - Q*S_liq*(1-f_rtn))/V_liq \
                    + np.dot(M_stoichio.T, rhos)
                q_gas = f_qgas(rhos[-3:], S_gas, T)
                _dstate[n_cmps: (n_cmps+n_gas)] = - q_gas*S_gas/V_gas \
                    + rhos[-3:] * V_liq/V_gas * gas_mass2mol_conversion
                _dstate[-1] = dQC_ins[0,-1]
                _update_dstate()
            self._ODE = dy_dt


# %%

ad_path = ospath.join(data_path, 'sanunit_data/_anaerobic_digestion.tsv')

class AnaerobicDigestion(SanUnit, Decay):
    '''
    Anaerobic digestion of wastes with the production of biogas based on
    `Trimmer et al. <https://doi.org/10.1021/acs.est.0c03296>`_

    To enable life cycle assessment, the following impact items should be pre-constructed:
    `Concrete`, `Excavation`.

    Cost is calculated by the unit cost of the impact items and their quantities.

    Parameters
    ----------
    ins : Iterable
        Waste for treatment.
    outs : Iterable
        Treated waste, captured biogas, fugitive CH4, and fugitive N2O.
    flow_rate : float
        Total flow rate through the reactor (for sizing purpose), [m3/d].
        If not provided, will use F_vol_in.
    degraded_components : tuple
        IDs of components that will degrade (at the same removal as `COD_removal`).
    if_capture_biogas : bool
        If produced biogas will be captured, otherwise it will be treated
        as fugitive CH4.
    if_N2O_emission : bool
        If consider N2O emission from N degradation in the process.

    Examples
    --------
    `bwaise systems <https://github.com/QSD-Group/EXPOsan/blob/main/exposan/bwaise/systems.py>`_

    References
    ----------
    [1] Trimmer et al., Navigating Multidimensional Social–Ecological System
    Trade-Offs across Sanitation Alternatives in an Urban Informal Settlement.
    Environ. Sci. Technol. 2020, 54 (19), 12641–12653.
    https://doi.org/10.1021/acs.est.0c03296.

    See Also
    --------
    :ref:`qsdsan.sanunits.Decay <sanunits_Decay>`
    '''

    def __init__(self, ID='', ins=None, outs=(), thermo=None, init_with='WasteStream',
                 flow_rate=None, degraded_components=('OtherSS',),
                 if_capture_biogas=True, if_N2O_emission=False,
                 **kwargs):
        SanUnit.__init__(self, ID, ins, outs, thermo, init_with)
        self._flow_rate = flow_rate
        self.degraded_components = tuple(degraded_components)
        self.if_capture_biogas = if_capture_biogas
        self.if_N2O_emission = if_N2O_emission

        self.construction = (
            Construction('concrete', linked_unit=self, item='Concrete', quantity_unit='m3'),
            Construction('excavation', linked_unit=self, item='Excavation', quantity_unit='m3'),
            )

        data = load_data(path=ad_path)
        for para in data.index:
            value = float(data.loc[para]['expected'])
            setattr(self, '_'+para, value)
        del data

        for attr, value in kwargs.items():
            setattr(self, attr, value)


    _N_ins = 1
    _N_outs = 4


    def _run(self):
        waste = self.ins[0]
        treated, biogas, CH4, N2O = self.outs
        treated.copy_like(self.ins[0])
        biogas.phase = CH4.phase = N2O.phase = 'g'

        # COD removal
        _COD = waste._COD or waste.COD
        COD_deg = _COD*treated.F_vol/1e3*self.COD_removal # kg/hr
        treated._COD *= (1-self.COD_removal)
        treated.imass[self.degraded_components] *= (1-self.COD_removal)

        CH4_prcd = COD_deg*self.MCF_decay*self.max_CH4_emission
        if self.if_capture_biogas:
            biogas.imass['CH4'] = CH4_prcd
            CH4.empty()
        else:
            CH4.imass['CH4'] = CH4_prcd
            biogas.empty()

        if self.if_N2O_emission:
            N_loss = self.first_order_decay(k=self.decay_k_N,
                                            t=self.tau/365,
                                            max_decay=self.N_max_decay)
            N_loss_tot = N_loss*waste.TN/1e3*waste.F_vol
            NH3_rmd, NonNH3_rmd = \
                self.allocate_N_removal(N_loss_tot, waste.imass['NH3'])
            treated.imass['NH3'] = waste.imass['NH3'] - NH3_rmd
            treated.imass['NonNH3'] = waste.imass['NonNH3'] - NonNH3_rmd
            N2O.imass['N2O'] = N_loss_tot*self.N2O_EF_decay*44/28
        else:
            N2O.empty()

    _units = {
        'Volumetric flow rate': 'm3/hr',
        'Residence time': 'd',
        'Single reactor volume': 'm3',
        'Reactor diameter': 'm',
        'Reactor height': 'm'
        }

    def _design(self):
        design = self.design_results
        design['Volumetric flow rate'] = Q = self.flow_rate
        design['Residence time'] = tau = self.tau
        design['Reactor number'] = N = self.N_reactor
        V_tot = Q * tau*24

        # One extra as a backup
        design['Single reactor volume'] = V_single = V_tot/(1-self.headspace_frac)/(N-1)

        # Rx modeled as a cylinder
        design['Reactor diameter'] = D = (4*V_single*self.aspect_ratio/pi)**(1/3)
        design['Reactor height'] = H = self.aspect_ratio * D

        constr = self.construction
        concrete =  N*self.concrete_thickness*(2*pi/4*(D**2)+pi*D*H)
        constr[0].quantity = concrete
        constr[1].quantity = V_tot # excavation

        self.add_construction()


    @property
    def flow_rate(self):
        '''
        [float] Total flow rate through the reactor (for sizing purpose), [m3/d].
        If not provided, will calculate based on F_vol_in.
        '''
        return self._flow_rate if self._flow_rate else self.F_vol_in*24
    @flow_rate.setter
    def flow_rate(self, i):
        self._flow_rate = i

    @property
    def tau(self):
        '''[float] Residence time, [d].'''
        return self._tau
    @tau.setter
    def tau(self, i):
        self._tau = i

    @property
    def COD_removal(self):
        '''[float] Fraction of COD removed during treatment.'''
        return self._COD_removal
    @COD_removal.setter
    def COD_removal(self, i):
        self._COD_removal = i

    @property
    def N_reactor(self):
        '''[int] Number of reactors, float will be converted to the smallest integer.'''
        return self._N_reactor
    @N_reactor.setter
    def N_reactor(self, i):
        self._N_reactor = ceil(i)

    @property
    def aspect_ratio(self):
        '''[float] Diameter-to-height ratio of the reactor.'''
        return self._aspect_ratio
    @aspect_ratio.setter
    def aspect_ratio(self, i):
        self._aspect_ratio = i

    @property
    def headspace_frac(self):
        '''[float] Fraction of the reactor volume for headspace gas.'''
        return self._headspace_frac
    @headspace_frac.setter
    def headspace_frac(self, i):
        self._headspace_frac = i

    @property
    def concrete_thickness(self):
        '''[float] Thickness of the concrete wall.'''
        return self._concrete_thickness
    @concrete_thickness.setter
    def concrete_thickness(self, i):
        self._concrete_thickness = i


# %%

F_BM_pump = 1.18*(1+0.007/100) # 0.007 is for miscellaneous costs
default_F_BM = {
        'Pump': F_BM_pump,
        'Pump building': F_BM_pump,
        }
default_equipment_lifetime = {
    'Pump': 15,
    'Pump pipe stainless steel': 15,
    'Pump stainless steel': 15,
    }

class SludgeDigester(SanUnit):
    '''
    A conventional digester for anaerobic digestion of sludge as in
    `Shoener et al. <https://doi.org/10.1039/C5EE03715H>`_.

    Note that the `CompiledComponents` object set in system simulation must
    have defined `active_biomass`.

    Parameters
    ----------
    ins : Iterable
        Sludge for digestion.
    outs : Iterable
        Digested sludge, generated biogas.
    HRT : float
        Hydraulic retention time, [d].
    SRT : float
        Solids retention time, [d].
    T : float
        Temperature within the digester, [K].
    Y : float
        Biomass yield, [mg VSS/mg BOD].
    b : float
        Endogenous decay coefficient, [1/d].
    organics_conversion : float
        Conversion of the organics (i.e., COD) of the sludge in fraction (i.e., 0.7 for 70%).
    COD_factor : float
        Biomass-to-COD conversion factor, [g COD/g VSS].
    methane_yield : float
        Methane yield from the digested organics, [m3/kg].
    methane_fraction : float
        Fraction of methane in the biogas, the rest is assumed to be CO2.
    depth : float
        Side depth of the digester, [m].
    heat_transfer_coeff : dict
        Heat transfer coefficients for heat loss calculation, [W/m2/°C],
        keys should contain "wall", "floor", and "ceiling".
    wall_concrete_unit_cost : float
        Unit cost of the wall concrete, [UDS/ft3].
    slab_concrete_unit_cost : float
        Unit cost of the slab concrete, [UDS/ft3].
    excavation_unit_cost : float
        Unit cost of the excavation activity, [UDS/ft3].

    References
    ----------
    [1] Shoener, B. D.; Zhong, C.; Greiner, A. D.; Khunjar, W. O.; Hong, P.-Y.; Guest, J. S.
        Design of Anaerobic Membrane Bioreactors for the Valorization
        of Dilute Organic Carbon Waste Streams.
        Energy Environ. Sci. 2016, 9 (3), 1102–1112.
        https://doi.org/10.1039/C5EE03715H.

    '''
    _N_outs = 2
    
    # All in K
    _T_air = 17 + 273.15
    _T_earth = 10 + 273.15

    # All in ft
    _freeboard = 3
    _t_wall = 6/12
    _t_slab = 8/12

    # Pump building, all in ft
    _L_PB = 50
    _W_PB = 30
    _D_PB = 10

    # Excavation
    _excav_slope = 1.5 # horizontal/vertical
    _constr_access = 3 # ft

    auxiliary_unit_names = ('heat_exchanger',)

    def __init__(self, ID='', ins=None, outs=(), thermo=None, init_with='WasteStream',
                 HRT=20, SRT=20, T=35+273.15, Y=0.08, b=0.03,
                 organics_conversion=0.7, COD_factor=1.42,
                 methane_yield=0.4, methane_fraction=0.65,
                 depth=10,
                 heat_transfer_coeff=dict(wall=0.7, floor=1.7, ceiling=0.95),
                 wall_concrete_unit_cost=24, # from $650/yd3
                 slab_concrete_unit_cost=13, # from $350/yd3
                 excavation_unit_cost=0.3, # from $8/yd3
                 F_BM=default_F_BM, lifetime=default_equipment_lifetime,
                 F_BM_default=1, **kwargs):
        SanUnit.__init__(self, ID, ins, outs, thermo, init_with, F_BM_default=1)
        self.HRT = HRT
        self.SRT = SRT
        self.T = T
        self.Y = Y
        self.b = b
        self.organics_conversion = organics_conversion
        self.COD_factor = COD_factor
        self.methane_yield = methane_yield
        self.methane_fraction = methane_fraction
        self.depth = depth
        self.heat_transfer_coeff = heat_transfer_coeff
        self.heat_exchanger = hx = HXutility(None, None, None, T=T)
        self.heat_utilities = hx.heat_utilities
        self.wall_concrete_unit_cost = wall_concrete_unit_cost
        self.slab_concrete_unit_cost = slab_concrete_unit_cost
        self.excavation_unit_cost = excavation_unit_cost
        self.F_BM.update(F_BM)
        self._default_equipment_lifetime.update(lifetime)
        self.sludge_pump = WWTpump(
            ID=f'{ID}_sludge', ins=self.ins[0].proxy(), pump_type='',
            Q_mgd=None, add_inputs=(1,), capacity_factor=1.,
            include_pump_cost=True, include_building_cost=False,
            include_OM_cost=False)


    def _run(self):
        sludge, = self.ins
        digested, biogas = self.outs
        digested.T = biogas.T = self.T
        biogas.phase = 'g'

        # Biogas production estimation based on Example 13-5 of Metcalf & Eddy, 5th edn.
        Y, b, SRT = self.Y, self.b, self.SRT
        organics_conversion, COD_factor = self.organics_conversion, self.COD_factor
        methane_yield, methane_fraction = self.methane_yield, self.methane_fraction
        biomass_COD = sludge.imass['active_biomass'].sum()*1e3*24*1.42 # [g/d], 1.42 converts VSS to COD

        digested.mass = sludge.mass
        digested.imass['active_biomass'] = 0 # biomass-derived COD calculated separately
        substrate_COD = digested.COD*24*digested.F_vol # [g/d]

        tot_COD = biomass_COD + substrate_COD # [g/d]

        digestion_yield = Y*tot_COD*organics_conversion/(1+b*SRT) # [g/d]
        methane_vol = methane_yield*tot_COD*organics_conversion - COD_factor*digestion_yield

        # Update stream flows
        digested.imass['substrates'] *= (1-organics_conversion)
        digested.imass['active_biomass'] = \
            sludge.imass['active_biomass']*(1-organics_conversion)

        biogas.empty()
        biogas.ivol['CH4'] = methane_vol
        biogas.ivol['CO2'] = methane_vol/methane_fraction*(1-methane_fraction)


    _units = {
        'HRT': 'd',
        'SRT': 'd',
        'Volume': 'm3',
        'Surface area': 'm2',
        'Diameter': 'm',
        'Wall concrete': 'ft3',
        'Slab concrete': 'ft3',
        'Excavation': 'ft3',
        'Pump pipe stainless steel': 'kg',
        'Pump stainless steel': 'kg',
        }
    def _design(self):
        design = self.design_results
        sludge, = self.ins
        Q = sludge.F_vol * 24 # from m3/hr to m3/d

        # Dimensions
        design['SRT'] = self.SRT
        HRT = design['HRT'] = self.HRT
        V = design['Volume'] = Q * HRT # m3
        depth = design['depth'] = self.depth # m
        A = design['Surface area'] = V / depth # m2
        dia = design['Diameter']= (A*4/pi) ** 0.5 # m

        # Calculate needed heating
        T = self.T
        sludge_T = sludge.T
        sludge_H_in = sludge.H
        sludge.T = T
        sludge_H_at_T = sludge.H
        sludge.T = sludge_T
        duty = sludge_H_at_T - sludge_H_in

        # Heat loss
        coeff = self.heat_transfer_coeff
        A_wall = pi * dia * depth
        wall_loss = coeff['wall'] * A_wall * (T-self.T_air) # [W]
        floor_loss = coeff['floor'] * A * (T-self.T_earth) # [W]
        ceiling_loss = coeff['ceiling'] * A * (T-self.T_air) # [W]
        duty += (wall_loss+floor_loss+ceiling_loss)*60*60/1e3 # kJ/hr
        self.heat_exchanger.simulate_as_auxiliary_exchanger(duty, sludge)

        # Concrete usage
        ft_2_m = auom('ft').conversion_factor('m')
        design['Wall concrete'] = self.t_wall * pi*(dia*ft_2_m)*(depth*ft_2_m+self.freeboard)
        design['Slab concrete'] = 2 * self.t_slab * A*(ft_2_m**2) # floor and ceiling

        # Excavation
        design['Excavation'] = calculate_excavation_volume(
            self.L_PB, self.W_PB, self.D_PB, self.excav_slope, self.constr_access)

        # Pump
        sludge_pump = self.sludge_pump
        sludge_pump.simulate()
        design.update(sludge_pump.design_results)

    def _cost(self):
        D, C = self.design_results, self.baseline_purchase_costs
        #  F_BM, lifetime = self.F_BM, self._default_equipment_lifetime
        C['Wall concrete'] = D['Wall concrete'] * self.wall_concrete_unit_cost
        C['Slab concrete'] = D['Slab concrete'] * self.slab_concrete_unit_cost
        C['Excavation'] = D['Excavation'] * self.excavation_unit_cost
        sludge_pump = self.sludge_pump
        C.update(sludge_pump.baseline_purchase_costs)
        self.power_utility.rate = sludge_pump.power_utility.rate


    @property
    def T_air(self):
        '''[float] Temperature of the air, [K].'''
        return self._T_air
    @T_air.setter
    def T_air(self, i):
        self._T_air = i

    @property
    def T_earth(self):
        '''[float] Temperature of the air, [K].'''
        return self._T_earth
    @T_earth.setter
    def T_earth(self, i):
        self._T_earth = i

    @property
    def freeboard(self):
        '''[float] Freeboard added to the depth of the reactor tank, [ft].'''
        return self._freeboard
    @freeboard.setter
    def freeboard(self, i):
        self._freeboard = i

    @property
    def t_wall(self):
        '''[float] Concrete wall thickness, [ft].'''
        return self._t_wall
    @t_wall.setter
    def t_wall(self, i):
        self._t_wall = i

    @property
    def t_slab(self):
        '''
        [float] Concrete slab thickness, [ft],
        default to be 2 in thicker than the wall thickness.
        '''
        return self._t_slab or self.t_wall+2/12
    @t_slab.setter
    def t_slab(self, i):
        self._t_slab = i

    @property
    def L_PB(self):
        '''[float] Length of the pump building, [ft].'''
        return self._L_PB
    @L_PB.setter
    def L_PB(self, i):
        self._L_PB = i

    @property
    def W_PB(self):
        '''[float] Width of the pump building, [ft].'''
        return self._W_PB
    @W_PB.setter
    def W_PB(self, i):
        self._W_PB = i

    @property
    def D_PB(self):
        '''[float] Depth of the pump building, [ft].'''
        return self._D_PB
    @D_PB.setter
    def D_PB(self, i):
        self._D_PB = i

    @property
    def excav_slope(self):
        '''[float] Slope for excavation (horizontal/vertical).'''
        return self._excav_slope
    @excav_slope.setter
    def excav_slope(self, i):
        self._excav_slope = i

    @property
    def constr_access(self):
        '''[float] Extra room for construction access, [ft].'''
        return self._constr_access
    @constr_access.setter
    def constr_access(self, i):
        self._constr_access = i