'''
   external current source
'''
import numpy as np

from petram.phys.phys_model  import Phys, VectorPhysCoefficient
from petram.phys.em3d.em3d_base import EM3D_Bdry, EM3D_Domain

import petram.debug as debug
dprint1, dprint2, dprint3 = debug.init_dprints('EM3D_extJ')

from petram.mfem_config import use_parallel
if use_parallel:
   import mfem.par as mfem
else:
   import mfem.ser as mfem

from petram.phys.vtable import VtableElement, Vtable      
data =  (('jext', VtableElement('jext', type='complex',
                             guilabel = 'External J',
                             suffix =('x', 'y', 'z'),
                             default = [0,0,0],
                             tip = "volumetric external current" )),)
   
class Jext(VectorPhysCoefficient):
   def __init__(self, *args, **kwargs):
       self.omega = kwargs.pop('omega', 1.0)
       super(Jext, self).__init__(*args, **kwargs)
   def EvalValue(self, x):
       from em3d_const import mu0, epsilon0      
       v = super(Jext, self).EvalValue(x)
       v = 1j * self.omega * v
       if self.real:  return v.real
       else: return v.imag

class EM3D_ExtJ(EM3D_Domain):
    is_secondary_condition = True
    has_3rd_panel = False    
    vt  = Vtable(data)
    
    def has_lf_contribution(self, kfes = 0):
        if kfes != 0: return False
        return True

    def add_lf_contribution(self, engine, b, real = True, kfes = 0):
        if kfes != 0: return        
        if real:       
            dprint1("Add LF contribution(real)" + str(self._sel_index))
        else:
            dprint1("Add LF contribution(imag)" + str(self._sel_index))
            
        freq, omega = self.get_root_phys().get_freq_omega()
        f_name = self.vt.make_value_or_expression(self)

        coeff1 = Jext(3, f_name[0],  self.get_root_phys().ind_vars,
                            self._local_ns, self._global_ns,
                            real = real, omega = omega)
        
        self.add_integrator(engine, 'jext', coeff1,
                            b.AddDomainIntegrator,
                            mfem.VectorFEDomainLFIntegrator)

        '''
        coeff1 = self.restrict_coeff(coeff1, engine, vec = True)
        b.AddDomainIntegrator(mfem.VectorFEDomainLFIntegrator(coeff1))
        '''

