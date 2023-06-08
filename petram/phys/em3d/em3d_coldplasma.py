'''
   cold plasma.
'''
import numpy as np

from petram.mfem_config import use_parallel, get_numba_debug

from petram.phys.vtable import VtableElement, Vtable
from petram.phys.em3d.em3d_const import mu0, epsilon0
from petram.phys.coefficient import SCoeff, VCoeff, MCoeff
from petram.phys.numba_coefficient import NumbaCoefficient

from petram.phys.phys_model import MatrixPhysCoefficient, PhysCoefficient, PhysConstant, PhysMatrixConstant
from petram.phys.em3d.em3d_base import EM3D_Bdry, EM3D_Domain

import petram.debug as debug
dprint1, dprint2, dprint3 = debug.init_dprints('EM3D_ColdPlasma')

if use_parallel:
    import mfem.par as mfem
    from mpi4py import MPI
    myid = MPI.COMM_WORLD.rank
else:
    import mfem.ser as mfem
    myid = 0

data = (('B', VtableElement('bext', type='array',
                            guilabel='magnetic field',
                            default="=[0,0,0]",
                            tip="external magnetic field")),
        ('dens_e', VtableElement('dens_e', type='float',
                                 guilabel='electron density(m-3)',
                                 default="1e19",
                                 tip="electron density")),
        ('temperature', VtableElement('temperature', type='float',
                                      guilabel='electron temp.(eV)',
                                      default="10.",
                                      tip="electron temperature used for collisions")),
        ('dens_i', VtableElement('dens_i', type='array',
                                 guilabel='ion densities(m-3)',
                                 default="0.9e19, 0.1e19",
                                 tip="ion densities")),
        ('mass', VtableElement('mass', type='array',
                               guilabel='ion masses(/Da)',
                               default="2, 1",
                               no_func=True,
                               tip="mass. use  m_h, m_d, m_t, or u")),
        ('charge_q', VtableElement('charge_q', type='array',
                                   guilabel='ion charges(/q)',
                                   default="1, 1",
                                   no_func=True,
                                   tip="ion charges normalized by q(=1.60217662e-19 [C])")),)

'''
def Epsilon_Coeff(ind_vars, l, g, omega):
    # - omega^2 * epsilon0 * epsilonr
    exprs = [(1+0j), 0j, 0j, 0j, (1+0j), 0j, 0j, 0j, (1+0j)]
    fac = -epsilon0 * omega * omega
    coeff = MCoeff(3, exprs, ind_vars, l, g, return_complex=True, scale=fac)
    return coeff


def Sigma_Coeff(ind_vars, l, g, omega):
    exprs = [0j, 0j, 0j, 0j, 0j, 0j, 0j, 0j, 0j]
    fac = - 1j * omega
    coeff = MCoeff(3, exprs, ind_vars, l, g, return_complex=True, scale=fac)
    return coeff


def Mu_Coeff(ind_vars, l, g, omega):
    exprs = [(1+0j), 0j, 0j, 0j, (1+0j), 0j, 0j, 0j, (1+0j)]
    fac = mu0
    coeff = MCoeff(3, exprs, ind_vars, l, g, return_complex=True, scale=fac)
    return coeff
'''


def domain_constraints():
    return [EM3D_ColdPlasma]


class EM3D_ColdPlasma(EM3D_Domain):
    allow_custom_intorder = True
    vt = Vtable(data)
    #nlterms = ['epsilonr']

    def get_possible_child(self):
        from .em3d_pml import EM3D_LinearPML
        return [EM3D_LinearPML]

    def has_bf_contribution(self, kfes):
        if kfes == 0:
            return True
        else:
            return False

    @property
    def jited_coeff(self):
        return self._jited_coeff

    def compile_coeffs(self):
        self._jited_coeff = self.get_coeffs()

    def get_coeffs(self):
        from .em3d_const import mu0, epsilon0
        freq, omega = self.get_root_phys().get_freq_omega()
        B, dens_e, t_e, dens_i, masses, charges = self.vt.make_value_or_expression(
            self)
        ind_vars = self.get_root_phys().ind_vars

        from petram.phys.rf_dispersion_coldplasma import build_coefficients
        coeff1, coeff2, coeff3, coeff4 = build_coefficients(ind_vars, omega, B, dens_e, t_e,
                                                            dens_i, masses, charges,
                                                            self._global_ns, self._local_ns,)
        return coeff1, coeff2, coeff3, coeff4

    def add_bf_contribution(self, engine, a, real=True, kfes=0):
        if kfes != 0:
            return
        if real:
            dprint1("Add BF contribution(real)" + str(self._sel_index))
        else:
            dprint1("Add BF contribution(imag)" + str(self._sel_index))

        coeff1, coeff2, coeff3, coeff4 = self.jited_coeff
        self.set_integrator_realimag_mode(real)

        if self.has_pml():
            coeff1 = self.make_PML_coeff(coeff1)
            coeff2 = self.make_PML_coeff(coeff2)
            coeff3 = self.make_PML_coeff(coeff3)
        coeff2 = coeff2.inv()

        if self.allow_custom_intorder and self.add_intorder != 0:
            fes = a.FESpace()
            geom = fes.GetFE(0).GetGeomType()
            order = fes.GetFE(0).GetOrder()
            isPK = (fes.GetFE(0).Space() == mfem.FunctionSpace.Pk)
            orderw = fes.GetElementTransformation(0).OrderW()
            curlcurl_order = order*2 - 2 if isPK else order*2
            mass_order = orderw + 2*order
            curlcurl_order += self.add_intorder
            mass_order += self.add_intorder

            dprint1("Debug: custom int order. Increment = " +
                    str(self.add_intorder))
            dprint1("  FE order: " + str(order))
            dprint1("  OrderW: " + str(orderw))
            dprint1("  CurlCurlOrder: " + str(curlcurl_order))
            dprint1("  FEMassOrder: " + str(mass_order))

            cc_ir = mfem.IntRules.Get(geom, curlcurl_order)
            ms_ir = mfem.IntRules.Get(geom, mass_order)
        else:
            cc_ir = None
            ms_ir = None

        self.add_integrator(engine, 'epsilonr', coeff1,
                            a.AddDomainIntegrator,
                            mfem.VectorFEMassIntegrator,
                            ir=ms_ir)

        if coeff2 is not None:
            self.add_integrator(engine, 'mur', coeff2,
                                a.AddDomainIntegrator,
                                mfem.CurlCurlIntegrator,
                                ir=cc_ir)
            #coeff2 = self.restrict_coeff(coeff2, engine)
            # a.AddDomainIntegrator(mfem.CurlCurlIntegrator(coeff2))
        else:
            dprint1("No contrinbution from curlcurl")

        self.add_integrator(engine, 'sigma', coeff3,
                            a.AddDomainIntegrator,
                            mfem.VectorFEMassIntegrator,
                            ir=ms_ir)

    def add_domain_variables(self, v, n, suffix, ind_vars, solr, soli=None):
        from petram.helper.variables import add_expression, add_constant
        from petram.helper.variables import (NativeCoefficientGenBase,
                                             NumbaCoefficientVariable)

        if len(self._sel_index) == 0:
            return

        coeff1, coeff2, coeff3, coeff4 = self.jited_coeff

        c1 = NumbaCoefficientVariable(coeff1, complex=True, shape=(3, 3))
        c2 = NumbaCoefficientVariable(coeff1, complex=True, shape=(3, 3))
        c3 = NumbaCoefficientVariable(coeff1, complex=True, shape=(3, 3))
        c4 = NumbaCoefficientVariable(coeff1, complex=True, shape=(3, 3))

        ss = str(hash(self.fullname()))
        v["_e_"+ss] = c1
        v["_m_"+ss] = c2
        v["_s_"+ss] = c3
        v["_spd_"+ss] = c4

        self.do_add_matrix_expr(v, suffix, ind_vars, 'epsilonr', ["_e_"+ss])
        self.do_add_matrix_expr(v, suffix, ind_vars, 'mur', ["_m_"+ss])
        self.do_add_matrix_expr(v, suffix, ind_vars, 'sigma', ["_s_"+ss])
        self.do_add_matrix_expr(v, suffix, ind_vars,
                                'Sstix', ["_spd_"+ss+"[0,0]"])
        self.do_add_matrix_expr(v, suffix, ind_vars, 'Dstix', [
                                "1j*_spd_"+ss+"[0,1]"])
        self.do_add_matrix_expr(v, suffix, ind_vars,
                                'Pstix', ["_spd_"+ss+"[2,2]"])

        var = ['x', 'y', 'z']
        self.do_add_matrix_component_expr(v, suffix, ind_vars, var, 'epsilonr')
        self.do_add_matrix_component_expr(v, suffix, ind_vars, var, 'mur')
        self.do_add_matrix_component_expr(v, suffix, ind_vars, var, 'sigma')

        '''
        e, m, s = self.vt.make_value_or_expression(self)
        m = [(1+0j), 0j, 0j, 0j, (1+0j), 0j, 0j, 0j, (1+0j)]
        s = [0j, 0j, 0j, 0j, 0j, 0j, 0j, 0j, 0j]

        self.do_add_matrix_expr(v, suffix, ind_vars, 'epsilonr', e)
        self.do_add_matrix_expr(v, suffix, ind_vars, 'mur', m)
        self.do_add_matrix_expr(v, suffix, ind_vars, 'sigma', s)

        var = ['x', 'y', 'z']
        self.do_add_matrix_component_expr(v, suffix, ind_vars, var, 'epsilonr')
        self.do_add_matrix_component_expr(v, suffix, ind_vars, var, 'mur')
        self.do_add_matrix_component_expr(v, suffix, ind_vars, var, 'sigma')
        '''
