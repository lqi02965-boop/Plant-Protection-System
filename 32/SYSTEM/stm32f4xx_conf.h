/**
  ******************************************************************************
  * @file    stm32f4xx_conf.h
  * @brief   库配置文件（本工程裁剪版）
  ******************************************************************************
  * 基于 ST 官方 stm32f4xx_conf.h 模板改写:
  *   - 去掉 RTE_Components.h 依赖, 直接包含本工程用到的外设驱动头
  *   - 本工程用到: GPIO / RCC / USART / TIM / NVIC(misc)
  ******************************************************************************
  */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __STM32F4xx_CONF_H
#define __STM32F4xx_CONF_H

#if defined  (HSE_STARTUP_TIMEOUT)
  #undef HSE_STARTUP_TIMEOUT
#endif /* HSE_STARTUP_TIMEOUT */
#define HSE_STARTUP_TIMEOUT   ((uint16_t)0x05000) /*!< Time out for HSE start up */

/* Includes ------------------------------------------------------------------*/
#include "misc.h"
#include "stm32f4xx_gpio.h"
#include "stm32f4xx_rcc.h"
#include "stm32f4xx_tim.h"
#include "stm32f4xx_usart.h"

/* Exported macro ------------------------------------------------------------*/
#ifdef  USE_FULL_ASSERT

/**
  * @brief  The assert_param macro is used for function's parameters check.
  * @param  expr: If expr is false, it calls assert_failed function
  *   which reports the name of the source file and the source
  *   line number of the call that failed.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
  #define assert_param(expr) ((expr) ? (void)0 : assert_failed((uint8_t *)__FILE__, __LINE__))
/* Exported functions ------------------------------------------------------- */
  void assert_failed(uint8_t* file, uint32_t line);
#else
  #define assert_param(expr) ((void)0)
#endif /* USE_FULL_ASSERT */

#endif /* __STM32F4xx_CONF_H */
